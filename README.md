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
- **Embeddings**: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim vectors)
- **LLM**: Google Gemini 3.1 Flash Lite
- **Database**: Supabase with pgvector for semantic search
- **Package Management**: uv (Python), npm (frontend)

## Features

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
Detects comparison keywords ("changed", "before", "evolution") and fetches T&C fragments from multiple document versions, enabling temporal analysis of how terms have evolved.

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
│   ├── update_terms.py      # Scraper & embedder — reads from shared.json; skips unchanged content (hash check); keeps last 2 versions
│   └── pyproject.toml       # uv dependencies
├── database/       
│   └── schema.sql   # Table + match_documents RPC
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
```

### Database Setup

Run the SQL files in your Supabase SQL editor:

```sql
-- 1. Create table and base search function
-- (see database/schema.sql)

-- 2. Create version-aware search function
-- (see database/match_by_version.sql)
```

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

## Testing

```bash
# Backend (9 tests)
cd backend && uv run pytest tests/ -v

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
