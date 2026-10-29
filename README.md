# T&C Ninja 🥷

**RAG-powered multilingual analyzer for social media Terms & Conditions.**

T&C Ninja translates complex legal jargon from social media platforms into plain language. Ask it anything about what companies really do with your data, and it answers using only the official T&C documents — no hallucinations.

## Supported Platforms

| Platform | Status |
|----------|--------|
| Instagram | ✅ |
| TikTok | ✅ |
| X-Twitter | ✅ |
| Facebook | ✅ |
| YouTube | ✅ |
| LinkedIn | ✅ |
| Snapchat | ✅ |
| WhatsApp | ✅ |
| Telegram | ✅ |
| BeReal | ✅ |

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Frontend  │────▶│   Backend    │────▶│    Supabase      │
│  (Next.js)  │◀────│  (FastAPI)   │◀────│   (pgvector)     │
└─────────────┘     └──────┬───────┘     └──────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Gemini LLM  │
                    └──────────────┘
```

- **Frontend**: Next.js 16 + React 19 + Tailwind CSS 4
- **Backend**: FastAPI with streaming responses
- **Embeddings**: `multilingual-e5-small` (384-d, 512 tokens) via HuggingFace Inference API in the backend; configured once in `shared.json`
- **LLM**: Google Gemini 3.1 Flash Lite
- **Database**: Supabase with pgvector for semantic search
- **Package Management**: uv (Python), npm (frontend)

## Features

### Retrieval pipeline
Measured offline with `scripts/eval` (34 questions, EN + ES, incl. follow-ups): answer clause in the top-8 chunks went from **68% → 97%** (MRR 0.44 → ~0.85).

1. **Follow-up rewriting** — "and how long do they keep it?" becomes a standalone query using the conversation (skipped on the first message).
2. **Hybrid search** — vector similarity + Postgres full-text (Spanish/English), fused with Reciprocal Rank Fusion in `match_documents_hybrid`. Falls back to vector-only if the function isn't installed.
3. **LLM rerank** — Gemini picks the best 8 of 20 candidates (falls back to retrieval order on any error).
4. **Section-aware chunks** — 1000-char chunks that remember their heading path; the section is indexed but not quoted.

Switch off with `RAG_REWRITE=0` / `RAG_RERANK=0` (each adds one short Gemini call).

### Strict RAG (Retrieval-Augmented Generation)
The LLM only answers using actual T&C document fragments stored in Supabase. It never fabricates legal information. Every answer includes clickable references back to the source.

### Multilingual (i18n)
- Full UI in **English** and **Spanish** with runtime language switching
- Prompts, system instructions, and mode descriptions adapt to the selected language
- T&C documents scraped and embedded in both languages

### Auto-Detection of Platform Context
An AI classifier (Gemini Flash Lite) analyzes each user question to automatically detect which platforms are being discussed. If you mention "TikTok", the context switches — no manual selection needed.

### Response Modes
- **Explanation** — Plain language, colloquial tone. Translates legalese into everyday terms.
- **Legal** — Strict technical/legal terminology for professionals.

### Version-Aware Comparison
Detects comparison keywords ("changed", "before", "evolution") and fetches T&C fragments from the current version **and the one it deprecated**, enabling temporal analysis of how terms have evolved. Regular questions only ever see the **current** T&C: deprecated versions are never mixed into an answer, and in comparisons they are labelled `SUPERSEDED` so the model says they are no longer in force.

### Red Flag Carousel
An auto-scrolling carousel highlights the most concerning clauses from each selected platform. Each platform has 4 curated red flags in both languages.

### Modular Platform System — Single Source of Truth

All platform configuration lives in **one file**: [`frontend/config/shared.json`](frontend/config/shared.json).

This JSON is the canonical registry for all platforms and supported languages. All three layers of the app read from it:

| Consumer | How it reads |
|----------|-------------|
| **Frontend** (`config/platforms/index.ts`) | Native JSON import — no duplication |
| **Backend** (`main.py`) | `pathlib.Path` read at startup — `VALID_PLATFORMS` and `VALID_LANGUAGES` auto-derived |
| **Scripts** (`update_terms.py`) | Same path read — iterates platforms and scrape URLs |

**`frontend/config/shared.json`** structure:
```json
{
  "languages": ["es", "en"],
  "platforms": [
    {
      "id": "Instagram",
      "color": "#E1306C",
      "scrapeUrls": { "es": "...", "en": "..." },
      "icon": { "viewBox": "...", "elements": [...] },
      "redFlags": { "es": [...], "en": [...] }
    }
  ]
}
```

**To add a new platform** (only 1 step):
1. Add an entry to `frontend/config/shared.json` ← **the only change needed**
   - Include `id`, `color`, `scrapeUrls` (per language), `icon` (SVG data), and `redFlags` (per language)
   - Everything else — platform list, icons, red flag carousel, RAG validation — updates automatically

**To add a new language** (3 steps):
1. Add its code to `"languages"` in `shared.json` → backend `VALID_LANGUAGES` updates automatically; `redFlags` in `shared.json` gain a new key per platform
2. Create `frontend/locales/[lang].ts` and register it in `frontend/locales/index.ts` (2 lines)
3. Add prompts to `backend/prompts.py`

### Observability
- **Backend**: HTTP middleware logs every request with a shared correlation ID (e.g. `[ww2oo7mh]`) across `/detect-context` and `/ask`. Requests >5 s log as `⚡ SLOW`, >30 s as `⚠ VERY SLOW`. Per-phase timings (embed, RAG, LLM first-token) are logged individually.
- **Frontend**: `AbortController` shared across `/detect-context` + `/ask`. After **30 s** without any response, an overload warning appears in the chat (the request continues). After **2 min**, the request is hard-aborted and a connection error is shown. Dev-only `console.log` measures TTFB of the `/ask` stream.
- **Language fallback**: If no documents exist for the requested language, the backend automatically tries other languages and logs a warning.

### Input Validation
All user inputs are validated against whitelists:
- `platforms` → only names in `VALID_PLATFORMS` are accepted
- `mode` → falls back to `"explanation"` if invalid
- `language` → falls back to `"es"` if invalid

## Project Structure

```
tc-ninja/
├── backend/
│   ├── main.py              # FastAPI server (/ask, /detect-context)
│   ├── prompts.py           # LLM prompt templates (es/en)
│   ├── pyproject.toml       # uv dependencies
│   └── tests/
│       └── test_api.py      # 9 pytest tests
├── frontend/
│   ├── app/
│   │   ├── page.tsx         # Main chat UI component
│   │   ├── layout.tsx       # Root layout
│   │   └── globals.css      # Tailwind styles
│   ├── config/
│   │   ├── shared.json      # ← SINGLE SOURCE OF TRUTH (platforms + languages + icons + redFlags)
│   │   └── platforms/
│   │       ├── types.ts     # PlatformConfig interface (includes IconConfig, redFlags)
│   │       ├── index.ts     # Reads from shared.json
│   │       └── icons.tsx    # Generic SVG renderer — reads icon data from shared.json
│   ├── locales/             # i18n UI strings (en.ts, es.ts) — redFlags derived from shared.json
│   ├── tests/               # 17 vitest tests
│   ├── package.json
│   └── vitest.config.ts
├── scripts/
│   ├── update_terms.py      # Scraper & embedder — reads from shared.json; skips unchanged content (hash check); versions every change (current → superseded), purges old ones
│   ├── scraping.py          # Fetch (retries/backoff), cleaning, block-page validation, language detection
│   ├── fetchers.py          # Fetcher chain: Jina → direct (trafilatura) → Playwright, per-source overrides
│   ├── chunking.py          # Section-aware chunker
│   ├── changes.py           # Sentence-level diff between versions + Gemini changelog
│   ├── eval/                # Offline retrieval benchmark (questions.json + eval_retrieval.py)
│   ├── tests/               # scraper unit tests
│   └── pyproject.toml       # uv dependencies
├── database/       
│   ├── schema.sql           # Fresh install: tables, match_documents, activate_document_version
│   ├── migrations/          # 001 versioning · 002 hybrid search, embedding model, changelogs
│   └── tests/test_sql.py    # Runs the SQL on a real embedded Postgres + pgvector
└── README.md
```

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Supabase project with pgvector extension enabled

### Environment Variables

Create `.env` files in `backend/` and `scripts/`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
GEMINI_API_KEY=your-gemini-api-key
HF_TOKEN=your-huggingface-token
```

### Database Setup

Run in your Supabase SQL editor:

- **New database:** `database/schema.sql` (non-destructive, safe to re-run).
- **Existing database** (created before versioning): `database/migrations/001_document_versions.sql`, then `002_hybrid_search_and_changes.sql`, **before** deploying the new backend and scraper. They keep your chunks and mark the newest version of each platform/language as `current`.

See [PENDIENTE_SUPABASE.md](PENDIENTE_SUPABASE.md) for the exact rollout order.

### Backend

```bash
cd backend
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Scraping & Embedding T&C Documents

```bash
cd scripts
uv sync
uv run python update_terms.py
```

This scrapes T&C pages for all 10 platforms in both languages, splits them into chunks, generates embeddings, and stores them in Supabase.

**How T&C updates are handled**

1. Each source is downloaded through a **fetcher chain** — Jina reader → direct HTTP + trafilatura → headless Chromium (Playwright) — falling back whenever a result is blocked, too short or in the wrong language. Sources can override the chain in `shared.json` (`sourceFetchers`; Meta privacy pages and YouTube terms use it because Jina truncates or mis-localises them). Set `JINA_API_KEY` for a higher Jina rate limit. The text is cleaned (Jina header, images and link targets removed so volatile tokens don't look like changes) and validated (minimum size, login/bot-wall detection).
2. If the content hash equals the `current` version, nothing happens.
3. Otherwise the new text is stored as a `pending` version and then promoted with `activate_document_version()` in one transaction: the new version becomes `current` and the old one is **deprecated** (`superseded`). Searches switch over atomically and never see a half-loaded version.
4. Superseded versions beyond `MAX_VERSIONS_TO_KEEP` (3 including current) are deleted.
5. Every new version stores a sentence-level diff against the previous one plus a Gemini-written changelog (needs `GEMINI_API_KEY`; optional). "What changed?" questions get it as context.
6. A failed, blocked or suspiciously shrunk (<50%) scrape leaves the stored data untouched and makes the run exit non-zero (the GitHub Action turns red). `--force` overrides the hash and shrink checks.

## API Endpoints

### `POST /ask`
Streaming RAG endpoint. Returns an AI-generated analysis of the selected platforms' T&C.

```json
{
  "platforms": ["Instagram", "TikTok"],
  "messages": [{"role": "user", "content": "Who owns my photos?"}],
  "mode": "explanation",
  "language": "en"
}
```

### `POST /detect-context`
Auto-detects which platforms the user is asking about.

```json
{
  "message": "What does TikTok do with my data?",
  "current_platforms": ["Instagram"]
}
```

### `GET /versions`
Current T&C version, last-update date and changelog for each platform/language.

## Testing

```bash
# Backend
cd backend && uv run --group dev pytest tests/ -v

# Scraper
cd scripts && uv run --group dev pytest -v

# Retrieval benchmark (downloads and caches the corpus on first run; no database needed)
cd scripts && uv run python eval/eval_retrieval.py --chunk baseline --model minilm --search vector
cd scripts && uv run python eval/eval_retrieval.py --chunk 1000s --model e5-small --search hybrid --rewrite --rerank

# Frontend (17 tests)
cd frontend && npx vitest run
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Next.js 16, React 19, TypeScript 5, Tailwind CSS 4 |
| Backend | FastAPI, Pydantic, uvicorn |
| LLM | Google Gemini 3.1 Flash Lite |
| Embeddings | SentenceTransformers (MiniLM-L12-v2) |
| Database | Supabase + pgvector |
| Scraping | Jina Reader API |
| Testing | pytest + httpx (backend), vitest + testing-library (frontend) |
| Package Mgmt | uv (Python), npm (Node.js) |

## License

MIT
