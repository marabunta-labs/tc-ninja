"""Offline retrieval evaluation — no Supabase needed.

Builds an in-memory index from the cached corpus for each question's
platform/language and measures whether the evidence clause is among the top-k
chunks. Use it to compare chunking, embedding models, hybrid search, query
rewriting and reranking BEFORE changing production.

    cd scripts
    uv run python eval/eval_retrieval.py --chunk baseline --chunk 500s --model minilm
    uv run python eval/eval_retrieval.py --chunk 500s --search hybrid --rewrite --rerank
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import pickle
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "backend"))

import numpy as np  # noqa: E402

import corpus  # noqa: E402
from chunking import Chunk, chunk_document  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

MODELS = {
    "minilm": ("paraphrase-multilingual-MiniLM-L12-v2", "", ""),
    "e5-small": ("intfloat/multilingual-e5-small", "query: ", "passage: "),
}
KS = (1, 3, 5, 8, 12)
RRF_K = 60


def norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[*_#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- chunkers
def chunker(name: str):
    """'baseline' = legacy 1000/150 · '<size>' = plain · '<size>s' = section-aware."""
    if name == "baseline":
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=150, separators=["\n\n", "\n", ".", " ", ""]
        )
        return lambda text: [Chunk(c) for c in splitter.split_text(text)]
    with_sections = name.endswith("s")
    size = int(name.rstrip("s"))

    def run(text):
        chunks = chunk_document(text, size=size, overlap=max(50, size // 6))
        return chunks if with_sections else [Chunk(c.content) for c in chunks]

    return run


# --------------------------------------------------------------------------- models
_loaded = {}


def encode(model_key: str, texts: list[str], kind: str) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    name, q_prefix, p_prefix = MODELS[model_key]
    prefix = q_prefix if kind == "query" else p_prefix
    texts = [prefix + t for t in texts]
    digest = hashlib.sha256((name + "\n".join(texts)).encode()).hexdigest()[:24]
    cache_file = corpus.CACHE / f"emb_{digest}.npy"
    if cache_file.exists():
        return np.load(cache_file)
    if model_key not in _loaded:
        _loaded[model_key] = SentenceTransformer(name)
    vectors = _loaded[model_key].encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    np.save(cache_file, vectors)
    return vectors


# --------------------------------------------------------------------------- index
class Index:
    def __init__(self, platform: str, lang: str, chunk_name: str, model_key: str):
        self.chunks: list[Chunk] = []
        for _, text in corpus.get_documents(platform, lang):
            self.chunks.extend(chunker(chunk_name)(text))
        texts = [c.embed_text for c in self.chunks]
        self.vectors = encode(model_key, texts, "passage")
        self.model_key = model_key
        self.tokens = [re.findall(r"\w+", t.lower()) for t in texts]
        self.df = Counter(tok for toks in self.tokens for tok in set(toks))
        self.avg_len = sum(len(t) for t in self.tokens) / max(len(self.tokens), 1)

    def vector_rank(self, query: str) -> list[int]:
        q = encode(self.model_key, [query], "query")[0]
        return list(np.argsort(-(self.vectors @ q)))

    def bm25_rank(self, query: str, k1=1.5, b=0.75) -> list[int]:
        q_tokens = set(re.findall(r"\w+", query.lower()))
        n = len(self.tokens)
        scores = np.zeros(n)
        for i, toks in enumerate(self.tokens):
            tf = Counter(toks)
            for t in q_tokens:
                if t in tf:
                    idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    scores[i] += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(toks) / self.avg_len))
        return [int(i) for i in np.argsort(-scores) if scores[i] > 0]

    def hybrid_rank(self, query: str, pool: int = 20) -> list[int]:
        scores = Counter()
        for ranking in (self.vector_rank(query)[:pool], self.bm25_rank(query)[:pool]):
            for r, i in enumerate(ranking, 1):
                scores[int(i)] += 1 / (RRF_K + r)
        return [i for i, _ in scores.most_common()]


# --------------------------------------------------------------------------- evaluation
def first_hit(contents: list[str], evidence: list[str]) -> int | None:
    phrases = [norm(e) for e in evidence]
    for rank, content in enumerate(contents, 1):
        text = norm(content)
        if any(p in text for p in phrases):
            return rank
    return None


async def run_config(questions, args, chunk_name, model_key):
    indexes, results = {}, []
    client = rag = None
    if args.rewrite or args.rerank:
        from google import genai
        from dotenv import load_dotenv
        import rag as rag_module

        load_dotenv(HERE.parent.parent / "backend" / ".env")
        client, rag = genai.Client(api_key=os.environ["GEMINI_API_KEY"]), rag_module

    for q in questions:
        key = (q["platform"], q["lang"])
        if key not in indexes:
            indexes[key] = Index(*key, chunk_name, model_key)
        idx = indexes[key]

        query = q["q"]
        if args.rewrite and q.get("history"):
            query = await rag.rewrite_query(client, args.llm, [tuple(h) for h in q["history"]], query)

        pool = {"vector": idx.vector_rank, "bm25": idx.bm25_rank, "hybrid": idx.hybrid_rank}[args.search](query)
        if args.rerank:
            cands = pool[: args.pool]
            order = await rag.rerank(client, args.llm, query, [idx.chunks[i].content for i in cands], 12)
            pool = [cands[i] for i in order]
        contents = [idx.chunks[i].content for i in pool[:12]]
        results.append((q, first_hit(contents, q["evidence"]), query))
    return results


def validate_gold(questions) -> list[str]:
    bad = []
    for q in questions:
        text = norm(" ".join(t for _, t in corpus.get_documents(q["platform"], q["lang"])))
        if not any(norm(e) in text for e in q["evidence"]):
            bad.append(q["id"])
    return bad


def summarise(label: str, results) -> str:
    n = len(results)
    cells = [f"{sum(1 for _, h, _ in results if h and h <= k) / n:5.0%}" for k in KS]
    mrr = sum(1 / h for _, h, _ in results if h) / n
    return f"{label:44} " + " ".join(cells) + f"  {mrr:5.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", action="append", help="baseline | <size> | <size>s (repeatable)")
    ap.add_argument("--model", action="append", choices=MODELS, help="repeatable")
    ap.add_argument("--search", default="vector", choices=["vector", "bm25", "hybrid"])
    ap.add_argument("--rewrite", action="store_true")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--pool", type=int, default=20, help="candidates sent to the reranker")
    ap.add_argument("--llm", default="gemini-3.1-flash-lite")
    ap.add_argument("--only", help="substring filter on question id")
    ap.add_argument("-v", "--verbose", action="store_true", help="list missed questions")
    args = ap.parse_args()

    questions = json.loads((HERE / "questions.json").read_text())
    if args.only:
        questions = [q for q in questions if args.only in q["id"]]
    bad = validate_gold(questions)
    if bad:
        print(f"⚠ evidence not found in corpus for: {bad} (dropped)\n")
        questions = [q for q in questions if q["id"] not in bad]

    print(f"{'config':44} " + " ".join(f"hit@{k:<2}" for k in KS) + "    MRR")
    for chunk_name in args.chunk or ["baseline"]:
        for model_key in args.model or ["minilm"]:
            label = f"{chunk_name}/{model_key}/{args.search}" + ("+rw" if args.rewrite else "") + ("+rr" if args.rerank else "")
            results = asyncio.run(run_config(questions, args, chunk_name, model_key))
            print(summarise(label, results))
            if args.verbose:
                for q, hit, query in results:
                    if not hit or hit > 5:
                        print(f"     miss@5  {q['id']:16} hit={hit}  query={query!r}")


if __name__ == "__main__":
    main()
