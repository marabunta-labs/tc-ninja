"""T&C Ninja — FastAPI backend.

Exposes these endpoints:

* ``POST /detect-context``  — lightweight Gemini classifier that infers which
  social-media platforms a user question is about.
* ``POST /ask``             — full RAG pipeline: embed → Supabase vector search
  (current T&C only; deprecated versions just for comparisons) → Gemini streaming response.
* ``GET  /versions``        — current T&C version / last-update date per platform.

All platform and language configuration is loaded at startup from the shared
``frontend/config/shared.json`` file so there is a single source of truth.
"""
import os
import json
import asyncio
import math
import time
import re
import logging
import urllib.parse
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from supabase import ClientOptions, create_client
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from dotenv import load_dotenv
from typing import List

import rag
from prompts import SYSTEM_PROMPTS, DECISION_PROMPT, MODE_INSTRUCTIONS, OVERLOAD_MSG, CONTEXT_MESSAGES

load_dotenv()

# Validate required environment variables at startup
_REQUIRED_ENV = ["SUPABASE_URL", "SUPABASE_KEY", "GEMINI_API_KEY"]
_missing = [v for v in _REQUIRED_ENV if not os.getenv(v)]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")

_SHARED_CONFIG_PATH = Path(__file__).parent.parent / "frontend" / "config" / "shared.json"
_shared_config = json.loads(_SHARED_CONFIG_PATH.read_text())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("tc-ninja")

# Thresholds (ms) for slow-request warnings
SLOW_THRESHOLD_WARN_MS = 5_000    # warn in logs
SLOW_THRESHOLD_ERROR_MS = 30_000  # log as ERROR and tell the client

app = FastAPI(title="T&C Ninja API")

_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-Id"],
)

# Las apps de Marabunta Labs comparten proyecto de Supabase; tc-ninja vive en su esquema.
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"), options=ClientOptions(schema="tcninja"))
gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = "gemini-3.1-flash-lite"

EMBEDDING = _shared_config["embedding"]  # same model and dimensions the scraper indexes with

# RAG switches (measured with scripts/eval: hybrid + rerank is the best configuration)
RAG_RERANK = os.getenv("RAG_RERANK", "1") != "0"
RAG_REWRITE = os.getenv("RAG_REWRITE", "1") != "0"
FINAL_CHUNKS = 8          # chunks per platform handed to the LLM
RERANK_POOL = 20          # candidates the reranker chooses from


def l2_normalize(vector: list) -> list:
    """Gemini only returns unit-length vectors at full size; the truncated 384-d ones must be normalised by hand."""
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


async def embed(text: str) -> list:
    """Embed a *query* with the Gemini API (same model, dimensions and normalisation as the scraper)."""
    config = genai_types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=EMBEDDING["dimensions"])
    for attempt in range(3):
        try:
            response = await gemini.aio.models.embed_content(model=EMBEDDING["model"], contents=[text], config=config)
            return l2_normalize(list(response.embeddings[0].values))
        except genai_errors.APIError as e:
            if e.code not in (429, 500, 503) or attempt == 2:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """HTTP middleware that logs every request with timing and slow-request warnings.

    Reads the ``X-Request-Id`` header (set by the frontend) so that the
    ``/detect-context`` and ``/ask`` calls for the same user question share a
    single correlation ID in the logs.  Requests that exceed
    ``SLOW_THRESHOLD_WARN_MS`` are logged as WARNING; those that exceed
    ``SLOW_THRESHOLD_ERROR_MS`` are logged as ERROR.
    """
    # Use the client-supplied correlation ID so detect-context + ask share the same ID
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())[:8]
    start = time.perf_counter()

    logger.info("→ [%s] %s %s", req_id, request.method, request.url.path)

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start) * 1000

    if elapsed_ms >= SLOW_THRESHOLD_ERROR_MS:
        logger.error(
            "← [%s] %s %s %d  %.0f ms  ⚠ VERY SLOW",
            req_id, request.method, request.url.path, response.status_code, elapsed_ms,
        )
    elif elapsed_ms >= SLOW_THRESHOLD_WARN_MS:
        logger.warning(
            "← [%s] %s %s %d  %.0f ms  ⚡ SLOW",
            req_id, request.method, request.url.path, response.status_code, elapsed_ms,
        )
    else:
        logger.info(
            "← [%s] %s %s %d  %.0f ms",
            req_id, request.method, request.url.path, response.status_code, elapsed_ms,
        )

    return response


MAX_MESSAGE_CHARS = 4_000
MAX_HISTORY_MESSAGES = 20  # turns sent back to Gemini; older ones are dropped to bound cost


class Message(BaseModel):
    """A single turn in the conversation (role is ``'user'``, ``'model'``, or ``'system'``)."""

    role: str
    content: str = Field(max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    """Request body for ``POST /ask``."""

    platforms: List[str]
    messages: List[Message] = Field(min_length=1)
    mode: str = "explanation"
    language: str = "es"


VALID_PLATFORMS = {p["id"] for p in _shared_config["platforms"]}
VALID_MODES = set(MODE_INSTRUCTIONS["es"].keys())
VALID_LANGUAGES = set(_shared_config["languages"])


class DetectRequest(BaseModel):
    """Request body for ``POST /detect-context``."""

    message: str = Field(max_length=MAX_MESSAGE_CHARS)
    current_platforms: List[str]
    language: str = "es"

async def detect_platforms(question: str, current_platforms: List[str]) -> List[str]:
    """Use Gemini Flash Lite to infer which platforms a question is about.

    Sends a one-shot classification prompt and parses the comma-separated
    response.  Only names present in ``VALID_PLATFORMS`` are returned, so
    hallucinated platform names are silently discarded.
    """
    classifier_prompt = DECISION_PROMPT.format(
        question=question,
        current_platforms=current_platforms,
        valid_platforms=", ".join(sorted(VALID_PLATFORMS)),
    )

    try:
        response = await gemini.aio.models.generate_content(
            model=GEMINI_MODEL, contents=classifier_prompt
        )
        result = response.text.strip()
    except Exception as e:
        # Classifier outage or safety block: keep the current context instead of failing the chat.
        logger.warning("detect_platforms failed, keeping current context: %s", e)
        return []

    detections = [p.strip() for p in result.split(",")]
    return [p for p in detections if p in VALID_PLATFORMS]


@app.post("/detect-context")
async def detect_context(request: DetectRequest):
    """Infer the relevant platforms from a user message and return an optional context-switch notice.

    Sanitises ``current_platforms`` against the whitelist, runs the Gemini
    classifier, and computes a human-readable ``message`` describing any
    platforms that were added or removed.  Returns both the resolved platform
    list and the (possibly ``null``) context message.
    """
    request.current_platforms = [
        p for p in request.current_platforms if p in VALID_PLATFORMS
    ]
    auto_detected = await detect_platforms(request.message, request.current_platforms)

    context_message = None
    final_platforms = request.current_platforms

    if auto_detected:
        final_platforms = auto_detected
        added = [p for p in final_platforms if p not in request.current_platforms]
        removed = [p for p in request.current_platforms if p not in final_platforms]

        lang = request.language if request.language in CONTEXT_MESSAGES else "en"
        msgs = CONTEXT_MESSAGES[lang]

        if added and removed:
            context_message = msgs["add_remove"].format(
                added=", ".join(added), removed=", ".join(removed)
            )
        elif added:
            context_message = msgs["add"].format(added=", ".join(added))
        elif removed:
            context_message = msgs["remove"].format(platforms=", ".join(final_platforms))

    return {"platforms": final_platforms, "message": context_message}


# Whole words / stems (not substrings: "antes" must not match "constantes").
_COMPARISON_RE = re.compile(
    r"(?<!\w)(?:changed|changes|before|previous|updated|evolution|history|versions?|compare"
    r"|cambi\w*|diferencia\w*|antes|anterior(?:es)?|actualizad\w*|evoluci[oó]n|historial|versi[oó]n(?:es)?"
    r"|comparar?)(?!\w)",
    re.IGNORECASE,
)


def is_comparison_query(text: str) -> bool:
    """Return True if *text* contains a keyword that suggests a temporal comparison query."""
    return bool(_COMPARISON_RE.search(text))


_MARKDOWN_NOISE = re.compile(r"[*_#>`|\[\]()~]|^\s*[-+]\s+", re.MULTILINE)


def text_fragment_link(url: str, content: str, max_words: int = 12) -> str:
    """Build a ``#:~:text=`` link that highlights *content* on the source page.

    The chunk is markdown, the page is rendered text: markdown syntax is removed
    or the fragment would never match. ``-`` must be percent-encoded too, or it
    is read as the ``prefix-,text`` separator.
    """
    if "#" in url:
        return url
    words = _MARKDOWN_NOISE.sub(" ", content).split()
    snippet = " ".join(words[:max_words])
    if not snippet:
        return url
    encoded = urllib.parse.quote(snippet, safe="").replace("-", "%2D")
    return f"{url}#:~:text={encoded}"


def _chunk_to_context(doc: dict, status: str) -> dict:
    metadata = doc.get("metadata") or {}
    return {
        "content": doc["content"],
        "url": metadata.get("source_url", "URL not available"),
        "date": metadata.get("fetch_date", "Unknown date"),
        "section": metadata.get("section", ""),
        "version": doc.get("version") or metadata.get("version", "unknown"),
        "status": doc.get("version_status") or status,
    }


_hybrid_unavailable_logged = False


def search_chunks(query_vector: list | None, query_text: str, platform: str, language: str,
                  count: int, version: str | None = None) -> list:
    """Top *count* chunks for one platform/language.

    Hybrid (vector + full-text, fused with RRF) when the database has
    ``match_documents_hybrid``; otherwise plain vector search. ``version=None``
    searches only the CURRENT version, a tag searches exactly that version.
    ``query_vector=None`` (embedding service down) searches by full text only.
    """
    global _hybrid_unavailable_logged
    base = {
        "query_embedding": query_vector,
        "match_count": count,
        "filter_platforms": [platform],
        "filter_language": language,
    }
    try:
        params = dict(base, query_text=query_text, filter_embedding_model=EMBEDDING["id"])
        if version:
            params["filter_version"] = version
        return supabase.rpc("match_documents_hybrid", params).execute().data or []
    except Exception as e:
        if not _hybrid_unavailable_logged:
            logger.warning("hybrid search unavailable (run migration 002?), using vector search: %s", e)
            _hybrid_unavailable_logged = True
    if query_vector is None:
        return []  # plain vector search cannot run without a vector
    params = dict(base, match_threshold=0.05)
    if version:
        params["filter_version"] = version
    return supabase.rpc("match_documents", params).execute().data or []


def list_versions(platform: str, language: str, limit: int = 2) -> list:
    """Newest-first versions (current, then deprecated) that share the current embedding model."""
    resp = (
        supabase.table("document_versions")
        .select("version, status, fetched_at, superseded_at, changes, embedding_model")
        .eq("platform", platform)
        .eq("language", language)
        .in_("status", ["current", "superseded"])
        .order("id", desc=True)
        .limit(limit + 3)
        .execute()
    )
    rows = resp.data or []
    # Versions embedded with another model can't be compared by vector; they stay reachable by full-text only.
    comparable = [r for r in rows if r.get("embedding_model") in (None, EMBEDDING["id"])]
    return (comparable or rows)[:limit]


def retrieve_context(platform: str, query_vector: list | None, query_text: str, language: str,
                     comparison: bool, pool: int = FINAL_CHUNKS) -> dict:
    """Blocking retrieval for one platform (run it in a worker thread).

    Regular questions only get the **current** T&C (falling back to another language if
    none exist), returning up to *pool* candidates. Comparison questions get the current
    version plus the one it deprecated, each chunk tagged with its status, and the stored
    changelog of the newest version.
    """
    if comparison:
        chunks, changelog = [], None
        for v in list_versions(platform, language):
            docs = search_chunks(query_vector, query_text, platform, language, 4, version=v["version"])
            chunks.extend(_chunk_to_context(d, v["status"]) for d in docs)
            if changelog is None and (v.get("changes") or {}).get("summary"):
                changelog = {"version": v["version"], "against": v["changes"].get("previous_version"),
                             "summary": v["changes"]["summary"]}
        return {"chunks": chunks, "changelog": changelog}

    langs_to_try = [language] + [l for l in _shared_config["languages"] if l != language]
    for lang in langs_to_try:
        t_rag = time.perf_counter()
        docs = search_chunks(query_vector, query_text, platform, lang, pool)
        logger.info("rag %s/%s %.0f ms  %d docs", platform, lang, (time.perf_counter() - t_rag) * 1000, len(docs))
        if docs:
            if lang != language:
                logger.warning("lang fallback: %s has no data for '%s', using '%s'", platform, language, lang)
            return {"chunks": [_chunk_to_context(d, "current") for d in docs], "changelog": None}
    return {"chunks": [], "changelog": None}


async def gather_platform_context(platform: str, query_vector: list | None, query_text: str, language: str,
                                  comparison: bool) -> dict:
    """Retrieve (in a thread) and, for regular questions, rerank the candidates with Gemini."""
    use_rerank = RAG_RERANK and not comparison
    result = await asyncio.to_thread(
        retrieve_context, platform, query_vector, query_text, language, comparison,
        RERANK_POOL if use_rerank else FINAL_CHUNKS,
    )
    chunks = result["chunks"]
    if use_rerank and len(chunks) > 1:
        t_rr = time.perf_counter()
        order = await rag.rerank(gemini, GEMINI_MODEL, query_text, [c["content"] for c in chunks], FINAL_CHUNKS)
        logger.info("rerank %s %.0f ms", platform, (time.perf_counter() - t_rr) * 1000)
        result["chunks"] = [chunks[i] for i in order]
    else:
        result["chunks"] = chunks[:FINAL_CHUNKS]
    return result


@app.get("/versions")
async def versions():
    """Current T&C version, last-update date and changelog per platform/language."""
    resp = await asyncio.to_thread(
        lambda: supabase.table("document_versions")
        .select("platform, language, version, fetched_at, activated_at, changes")
        .eq("status", "current")
        .execute()
    )
    return {"versions": resp.data or []}


@app.post("/ask")
async def ask_ninja(request: ChatRequest):
    """Streaming RAG endpoint — embed the query, fetch relevant T&C chunks, and stream a Gemini answer.

    Pipeline:
    1. Sanitise inputs (platforms, mode, language) against whitelists.
    2. Rewrite follow-up questions into standalone queries and embed them.
    3. Retrieve, per platform and in parallel, the most relevant chunks of the
       **current** T&C (hybrid vector + full-text search, reranked by Gemini).
       Deprecated versions are only retrieved for comparison queries, labelled
       as superseded and accompanied by the stored changelog.
    4. Format the chunks with clickable ``#:~:text=`` source links.
    5. Send the assembled prompt to Gemini and stream the response back.
    """
    request.platforms = [p for p in request.platforms if p in VALID_PLATFORMS]
    if not request.platforms:
        return StreamingResponse(
            iter(["No valid platforms selected."]), media_type="text/plain"
        )
    if request.mode not in VALID_MODES:
        request.mode = "explanation"
    if request.language not in VALID_LANGUAGES:
        request.language = "es"

    last_user_message = request.messages[-1].content

    final_platforms = request.platforms
    comparison_mode = is_comparison_query(last_user_message)

    history_pairs = [
        ("user" if m.role == "user" else "model", m.content)
        for m in request.messages[:-1][-MAX_HISTORY_MESSAGES:]
        if m.role != "system"
    ]

    try:
        # A follow-up like "and how long do they keep it?" is meaningless to a search engine:
        # turn it into a standalone query using the conversation.
        search_query = last_user_message
        if RAG_REWRITE and history_pairs:
            t_rw = time.perf_counter()
            search_query = await rag.rewrite_query(gemini, GEMINI_MODEL, history_pairs, last_user_message)
            logger.info("rewrite %.0f ms: %r", (time.perf_counter() - t_rw) * 1000, search_query)
            comparison_mode = comparison_mode or is_comparison_query(search_query)

        t0 = time.perf_counter()
        try:
            query_vector = await embed(search_query)
            logger.info("embed %.0f ms", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            # Embedding quota/outage must not take the chat down: the database falls back to full-text search.
            logger.warning("embedding unavailable, using full-text search only: %s", e)
            query_vector = None

        retrieved = await asyncio.gather(*(
            gather_platform_context(p, query_vector, search_query, request.language, comparison_mode)
            for p in final_platforms
        ))
    except Exception as e:
        logger.error("retrieval error: %s", e)
        return StreamingResponse(iter(["Ninja out of service. Please try again later."]), media_type="text/plain")

    context_sections = {p: r for p, r in zip(final_platforms, retrieved) if r["chunks"]}

    context_formatted = ""
    for p, section_data in context_sections.items():
        chunks = section_data["chunks"]
        context_formatted += f"--- DATA FROM {p.upper()} ---\n"
        if comparison_mode and len({c["version"] for c in chunks}) < 2:
            context_formatted += "(Only one stored version exists: there is no earlier version to compare against.)\n"
        changelog = section_data["changelog"]
        if changelog:
            context_formatted += (
                f"[AUTOMATIC CHANGELOG — version {changelog['version']} vs {changelog['against']}]\n"
                f"{changelog['summary']}\n\n"
            )
        for chunk_data in chunks:
            real_url = chunk_data["url"].replace("https://r.jina.ai/", "")
            exact_link = text_fragment_link(real_url, chunk_data["content"])
            if chunk_data["status"] == "superseded":
                status_tag = "SUPERSEDED — deprecated, no longer in force"
            else:
                status_tag = "CURRENT"
            section_tag = f" | Section: {chunk_data['section']}" if chunk_data["section"] else ""
            context_formatted += (
                f"[Source: {exact_link} | Fetched: {chunk_data['date']} | "
                f"Version: {chunk_data['version']} | Status: {status_tag}{section_tag}]\n"
                f"{chunk_data['content']}\n\n"
            )

    if not context_formatted:
        context_formatted = "No specific fragments found for the selected platforms."

    try:
        platforms_str = " and ".join(final_platforms)

        history = []
        for msg in request.messages[:-1][-MAX_HISTORY_MESSAGES:]:
            if msg.role != "system":
                history.append(
                    genai_types.Content(
                        role="user" if msg.role == "user" else "model",
                        parts=[genai_types.Part(text=msg.content)],
                    )
                )
        # Gemini rejects a history that does not start with a user turn (the cap can cut mid-pair).
        while history and history[0].role != "user":
            history.pop(0)

        chat = gemini.aio.chats.create(model=GEMINI_MODEL, history=history)

        mode_instruction = MODE_INSTRUCTIONS.get(request.language, MODE_INSTRUCTIONS["es"]).get(
            request.mode, MODE_INSTRUCTIONS.get(request.language, MODE_INSTRUCTIONS["es"])["explanation"]
        )

        system_prompt = SYSTEM_PROMPTS.get(request.language, SYSTEM_PROMPTS["es"])
        formatted_prompt = system_prompt.format(
            platform=platforms_str,
            context=context_formatted,
            mode_instructions=mode_instruction,
        )

        full_query = f"{formatted_prompt}\n\n---\nUSER QUESTION: {last_user_message}"

        t_llm = time.perf_counter()
        for attempt in range(3):
            try:
                response = await chat.send_message_stream(full_query)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                logger.warning("gemini send failed (attempt %d), retrying: %s", attempt + 1, e)
                await asyncio.sleep(1.5 * (attempt + 1))

        async def stream_generator():
            first_chunk = True
            try:
                async for chunk in response:
                    if chunk.text:
                        if first_chunk:
                            llm_ms = (time.perf_counter() - t_llm) * 1000
                            logger.info("llm first-token %.0f ms", llm_ms)
                            first_chunk = False
                        # Typing effect: emit char by char with a tiny pause
                        for char in chunk.text:
                            yield char
                            await asyncio.sleep(0.001)
            except Exception as e:
                total_ms = (time.perf_counter() - t_llm) * 1000
                if total_ms >= SLOW_THRESHOLD_ERROR_MS:
                    logger.error("llm timeout after %.0f ms: %s", total_ms, e)
                    overload_msg = OVERLOAD_MSG.get(request.language, OVERLOAD_MSG["en"])
                    yield overload_msg
                else:
                    logger.error("llm stream error: %s", e)
                    yield "\n\n⚠️ *The response was interrupted. Please try again.*"

        return StreamingResponse(stream_generator(), media_type="text/plain")

    except Exception as e:
        logger.error("ask error: %s", str(e))

        async def error_gen():
            yield "Ninja out of service. Please try again later."

        return StreamingResponse(error_gen(), media_type="text/plain")

@app.get("/health")
async def health_check():
    """Simple health check endpoint to verify that the backend is running."""

    return {"status": "ok", "ninja": "awake"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
