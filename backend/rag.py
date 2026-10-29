"""RAG helpers: follow-up query rewriting and LLM reranking.

Pure functions plus two async helpers that take the Gemini client as an
argument, so the same code is used by the API and by scripts/eval.
"""
import asyncio
import json
import logging
import re

logger = logging.getLogger("tc-ninja")

REWRITE_PROMPT = """You rewrite a user's follow-up question into ONE standalone search query over a social network's Terms & Conditions.

Rules:
- Resolve pronouns and references ("that", "it", "and what about...") using the conversation.
- Keep the language of the follow-up question.
- Keep the platform-agnostic legal topic (data, license, deletion, age, location...). Do not add facts.
- Output ONLY the query, one line, no quotes.

CONVERSATION:
{history}

FOLLOW-UP QUESTION: {question}

STANDALONE QUERY:"""

RERANK_PROMPT = """You rank fragments of Terms & Conditions by how directly they answer a question.

QUESTION: {question}

FRAGMENTS:
{fragments}

Return ONLY a JSON array with the numbers of the {top_k} fragments that best answer the question, most relevant first. Example: [3, 1, 7]"""

_MAX_HISTORY_TURNS = 4
_MAX_TURN_CHARS = 500
_FRAGMENT_PREVIEW_CHARS = 700


async def _generate(client, model: str, prompt: str, attempts: int = 2) -> str:
    """One Gemini call, retried once: "503 high demand" spikes are usually momentary."""
    for attempt in range(attempts):
        try:
            response = await client.aio.models.generate_content(model=model, contents=prompt)
            return response.text or ""
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(0.8)
    return ""


def format_history(history: list[tuple[str, str]]) -> str:
    """Last few (role, text) turns as plain text for the rewrite prompt."""
    turns = history[-_MAX_HISTORY_TURNS:]
    return "\n".join(f"{role.upper()}: {text[:_MAX_TURN_CHARS]}" for role, text in turns)


async def rewrite_query(client, model: str, history: list[tuple[str, str]], question: str) -> str:
    """Make a follow-up question self-contained. Falls back to *question* on any failure."""
    if not history:
        return question
    prompt = REWRITE_PROMPT.format(history=format_history(history), question=question)
    try:
        lines = (await _generate(client, model, prompt)).strip().splitlines()
        rewritten = lines[0].strip(" \"'") if lines else ""
        return rewritten if 3 <= len(rewritten) <= 400 else question
    except Exception as e:
        logger.warning("query rewrite failed, using original question: %s", e)
        return question


def parse_ranking(text: str, n_candidates: int) -> list[int]:
    """0-based candidate indices from the model's answer, deduplicated and range-checked."""
    match = re.search(r"\[[^\]]*\]", text or "")
    if not match:
        return []
    try:
        numbers = json.loads(match.group(0))
    except json.JSONDecodeError:
        numbers = [int(x) for x in re.findall(r"\d+", match.group(0))]
    seen, result = set(), []
    for x in numbers:
        if isinstance(x, int) and 1 <= x <= n_candidates and x not in seen:
            seen.add(x)
            result.append(x - 1)
    return result


async def rerank(client, model: str, question: str, contents: list[str], top_k: int) -> list[int]:
    """Indices of *contents* ordered by relevance (at most *top_k*).

    Candidates the model did not pick keep their original order after the picked
    ones, so a short or malformed answer never loses results.
    """
    if len(contents) <= 1:
        return list(range(len(contents)))
    fragments = "\n\n".join(
        f"[{i}] {c[:_FRAGMENT_PREVIEW_CHARS]}" for i, c in enumerate(contents, 1)
    )
    prompt = RERANK_PROMPT.format(question=question, fragments=fragments, top_k=min(top_k, len(contents)))
    try:
        picked = parse_ranking(await _generate(client, model, prompt), len(contents))
    except Exception as e:
        logger.warning("rerank failed, keeping retrieval order: %s", e)
        picked = []
    rest = [i for i in range(len(contents)) if i not in set(picked)]
    return (picked + rest)[:top_k]
