"""T&C Ninja — FastAPI backend.

Exposes two endpoints:

* ``POST /detect-context``  — lightweight Gemini classifier that infers which
  social-media platforms a user question is about.
* ``POST /ask``             — full RAG pipeline: embed → Supabase vector search
  → Gemini streaming response.

All platform and language configuration is loaded at startup from the shared
``frontend/config/shared.json`` file so there is a single source of truth.
"""
import os
import json
import asyncio
import time
import logging
import urllib.parse
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import create_client
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List

from prompts import SYSTEM_PROMPTS, DECISION_PROMPT, MODE_INSTRUCTIONS, OVERLOAD_MSG, CONTEXT_MESSAGES

load_dotenv()

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


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


class Message(BaseModel):
    """A single turn in the conversation (role is ``'user'``, ``'model'``, or ``'system'``)."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Request body for ``POST /ask``."""

    platforms: List[str]
    messages: List[Message]
    mode: str = "explanation"
    language: str = "es"


VALID_PLATFORMS = {p["id"] for p in _shared_config["platforms"]}
VALID_MODES = set(MODE_INSTRUCTIONS["es"].keys())
VALID_LANGUAGES = set(_shared_config["languages"])


class DetectRequest(BaseModel):
    """Request body for ``POST /detect-context``."""

    message: str
    current_platforms: List[str]
    language: str = "es"

def detect_platforms(question: str, current_platforms: List[str]) -> List[str]:
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

    model_lite = genai.GenerativeModel("models/gemini-3.1-flash-lite-preview")
    response = model_lite.generate_content(classifier_prompt)

    result = response.text.strip()
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
    auto_detected = detect_platforms(request.message, request.current_platforms)
    
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


COMPARISON_KEYWORDS = [
    "changed", "cambio", "cambiado", "diferencia", "antes", "previous",
    "updated", "actualizado", "evolución", "evolution", "history",
    "historial", "version", "versión", "compare", "comparar",
]


def is_comparison_query(text: str) -> bool:
    """Return True if *text* contains a keyword that suggests a temporal comparison query."""
    lower = text.lower()
    return any(kw in lower for kw in COMPARISON_KEYWORDS)


def fetch_versioned_context(
    query_vector: list, platform: str, language: str, version: str, count: int = 4
) -> list:
    """Retrieve the top *count* document chunks for a specific platform version.

    Calls the ``match_documents`` Supabase RPC with the optional
    ``filter_version`` parameter to restrict results to the given version tag.
    Used exclusively for comparison (temporal) queries.
    """
    rpc_params = {
        "query_embedding": query_vector,
        "match_threshold": 0.05,
        "match_count": count,
        "filter_platforms": [platform],
        "filter_language": language,
        "filter_version": version,
    }
    response = supabase.rpc("match_documents", rpc_params).execute()
    return response.data or []


@app.post("/ask")
async def ask_ninja(request: ChatRequest):
    """Streaming RAG endpoint — embed the query, fetch relevant T&C chunks, and stream a Gemini answer.

    Pipeline:
    1. Sanitise inputs (platforms, mode, language) against whitelists.
    2. Embed the last user message with SentenceTransformer.
    3. For each platform, retrieve the most relevant document chunks from
       Supabase via ``match_documents`` (with language fallback). For comparison
       queries the same RPC is called with an explicit ``filter_version``.
    4. Format the retrieved chunks with clickable source URLs using
       ``#:~:text=`` text fragments.
    5. Send the assembled prompt to Gemini and stream the response
       character-by-character back to the client.
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

    t0 = time.perf_counter()
    query_vector = model.encode(last_user_message).tolist()
    logger.info("embed %.0f ms", (time.perf_counter() - t0) * 1000)

    final_platforms = request.platforms
    context_sections = {}
    comparison_mode = is_comparison_query(last_user_message)

    for p in final_platforms:
        if comparison_mode:
            versions_resp = supabase.table("documents") \
                .select("metadata->version") \
                .eq("platform", p) \
                .eq("language", request.language) \
                .execute()

            distinct_versions = sorted(
                {r.get("version") for r in (versions_resp.data or []) if r.get("version")},
                reverse=True,
            )

            context_sections[p] = []
            for ver in distinct_versions[:2]:
                docs = fetch_versioned_context(
                    query_vector, p, request.language, ver, count=4
                )
                for doc in docs:
                    metadata = doc.get("metadata", {})
                    context_sections[p].append({
                        "content": doc["content"],
                        "url": metadata.get("source_url", "URL not available"),
                        "date": metadata.get("fetch_date", "Unknown date"),
                        "version": ver,
                    })
        else:
            # Try requested language; fall back to the first available language
            langs_to_try = [request.language] + [
                lang for lang in _shared_config["languages"] if lang != request.language
            ]
            docs_found = []
            used_lang = request.language
            for lang in langs_to_try:
                t_rag = time.perf_counter()
                rpc_params = {
                    "query_embedding": query_vector,
                    "match_threshold": 0.05,
                    "match_count": 8,
                    "filter_platforms": [p],
                    "filter_language": lang,
                }
                resp = supabase.rpc("match_documents", rpc_params).execute()
                logger.info("rag %s/%s %.0f ms  %d docs", p, lang, (time.perf_counter() - t_rag) * 1000, len(resp.data or []))
                if resp.data:
                    docs_found = resp.data
                    used_lang = lang
                    break

            if docs_found:
                if used_lang != request.language:
                    logger.warning("lang fallback: %s has no data for '%s', using '%s'", p, request.language, used_lang)
                context_sections[p] = []
                for doc in docs_found:
                    metadata = doc.get("metadata", {})
                    context_sections[p].append({
                        "content": doc["content"],
                        "url": metadata.get("source_url", "URL not available"),
                        "date": metadata.get("fetch_date", "Unknown date"),
                    })

    context_formatted = ""
    for p, chunks in context_sections.items():
        context_formatted += f"--- DATA FROM {p.upper()} ---\n"
        for chunk_data in chunks:
            real_url = chunk_data["url"].replace("https://r.jina.ai/", "")
            # Use first 15 words of the chunk for a more precise text fragment.
            # The URL already points to the correct language page (even after lang fallback)
            # because source_url is stored per-language in the metadata.
            words = chunk_data["content"].split()
            search_snippet = " ".join(words[:15])
            if search_snippet:
                encoded_text = urllib.parse.quote(search_snippet)
                exact_link = f"{real_url}#:~:text={encoded_text}"
            else:
                exact_link = real_url

            version_tag = ""
            if "version" in chunk_data:
                version_tag = f" | Version: {chunk_data['version']}"

            context_formatted += (
                f"[Source: {exact_link} | Fetched: {chunk_data['date']}{version_tag}]\n"
                f"{chunk_data['content']}\n\n"
            )

    if not context_formatted:
        context_formatted = "No specific fragments found for the selected platforms."

    try:
        platforms_str = " and ".join(final_platforms)

        history = []
        for msg in request.messages[:-1]:
            if msg.role != "system":
                history.append(
                    {
                        "role": "user" if msg.role == "user" else "model",
                        "parts": [msg.content],
                    }
                )

        model_name = "models/gemini-3.1-flash-lite-preview"
        gemini_hub = genai.GenerativeModel(model_name)
        chat = gemini_hub.start_chat(history=history)

        mode_instruction = MODE_INSTRUCTIONS.get(request.language, MODE_INSTRUCTIONS["es"]).get(
            request.mode, MODE_INSTRUCTIONS.get(request.language, MODE_INSTRUCTIONS["es"])["explanation"]
        )

        system_prompt = SYSTEM_PROMPTS.get(request.language, SYSTEM_PROMPTS["es"])
        formatted_prompt = system_prompt.format(
            platform=platforms_str,
            context=context_formatted,
            mode_instructions=mode_instruction,
        )

        full_query = f"{formatted_prompt}\n\nUSER QUESTION: {last_user_message}"

        t_llm = time.perf_counter()
        response = await chat.send_message_async(full_query, stream=True)

        async def stream_generator():
            first_chunk = True
            try:
                async for chunk in response:
                    if chunk.text:
                        if first_chunk:
                            llm_ms = (time.perf_counter() - t_llm) * 1000
                            logger.info("llm first-token %.0f ms", llm_ms)
                            first_chunk = False
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
                    yield f"\n\n[Streaming error: {str(e)}]"

        return StreamingResponse(stream_generator(), media_type="text/plain")

    except Exception as e:
        error_message = str(e)
        logger.error("ask error: %s", error_message)

        async def error_gen():
            yield f"Ninja out of service: {error_message}"
            
        return StreamingResponse(error_gen(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
