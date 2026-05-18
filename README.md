# Document Q&A System

Upload a folder of mixed documents — PDF, Markdown, plain text — and ask natural-language questions about what's in them.

## Stack

- **Backend**: FastAPI + asyncpg + PostgreSQL/pgvector
- **Frontend**: Next.js + Tailwind CSS
- **NLP**: spaCy entity extraction + sentence-transformers embeddings
- **Infra**: Docker Compose (Postgres, Redis, API server)

## Setup

```bash
# Start infrastructure
docker-compose up -d

# Install Python dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Configure environment
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/docqa"
export OPENAI_API_KEY="your-key-here"

# Run backend
python server.py
```

Frontend:
```bash
cd frontend && npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Supported formats

PDF, Markdown (`.md`), plain text (`.txt`)

## Database Schema

Two-table design:

**`documents`** — one row per uploaded file. Tracks filename, format, word count, processing status, and upload timestamp.

**`document_chunks`** — one row per text chunk. Each chunk stores:
- `chunk_text` — the raw passage (512-token window, 50-token overlap)
- `entities` — JSONB: `{ "people": [...], "dates": [...], "topics": [...], "file_refs": [...] }`
- `embedding` — `vector(384)` for pgvector similarity search

The embedding column is in the schema from the start even though semantic search isn't wired into the query path yet. Paying the schema cost upfront means activating it later is a one-line code change, not a migration against a live table.

```sql
-- Apply with: psql docqa < database/schema.sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents ( ... );
CREATE TABLE document_chunks (
    ...
    entities    JSONB,
    embedding   vector(384)
);
CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops);
```

## Ingestion Pipeline

Documents go through four stages before they're queryable:

```
File → DocumentProcessor → EntityExtractor → EmbeddingPipeline → PostgreSQL
```

**1. DocumentProcessor** — format detection and chunking
- PDF: `pdfplumber` page extraction
- Markdown: strips `#` headers and fence blocks, keeps prose
- Plain text: passthrough
- Chunks at 512 tokens with 50-token overlap so sentences aren't split mid-thought at boundaries

**2. EntityExtractor** — spaCy `en_core_web_sm`
- Extracts: `PERSON`, `DATE`, `ORG` → stored as `people`, `dates`, `topics`
- Custom regex patterns for file references (e.g. `REQ-\d+`, `filename.pdf`)
- Output is a JSONB dict per chunk, enabling SQL filtering by entity type later

**3. EmbeddingPipeline** — `sentence-transformers/all-MiniLM-L6-v2`
- 384-dimension vectors, stored in the `embedding vector(384)` column
- Model loads once at startup, runs inference per chunk

**4. TwoTierOrchestrator** — coordinates the above three stages, writes to PostgreSQL, updates processing status in Redis so the frontend can poll live progress

All four stages run async so document upload doesn't block concurrent chat queries.

## API

Two primary endpoints wired up:

**`POST /api/upload`** — accepts multipart file, runs the ingestion pipeline, returns document ID and chunk count.

**`POST /api/chat`** — takes `{ query, document_ids? }`, runs keyword search against `document_chunks`, returns a grounded response with source attribution.

**`GET /api/documents`** — lists all documents with status and metadata.

Search is currently a full-phrase `ILIKE` match against chunk text — simple and fast to implement, works for exact phrases. Keyword extraction and semantic reranking come next.

## Frontend

Next.js app with three panels:

- **Upload Documents** — drag-and-drop zone (or click to select) for PDF, MD, TXT. Shows upload progress and chunk count on completion.
- **Document Library** — table of uploaded documents with filename, format, word count, and processing status.
- **Chat** — ask a natural-language question, get a grounded answer with source document citations.

Stack: Next.js 14 + Tailwind CSS. No external component library — custom `Header`, `Sidebar`, and `Toast` components. API calls go through `src/lib/api.ts` which wraps `fetch` against the FastAPI backend on port 8000.

## Bug Fixes

**Full-phrase search returned zero results** — the initial `/api/chat` implementation used a single `WHERE chunk_text ILIKE '%{full query}%'`, so a question like "What are the main topics?" matched nothing because no chunk contains that exact phrase. The fix was to first remove the try/except fallback that was masking the failure (it silently returned "I couldn't find any documents" for all errors), expose the real behaviour, then fix root cause: extract individual keywords with a stopword filter and run `ILIKE ANY(keywords)` so each keyword matches independently.

**CORS headers missing on error responses** — FastAPI's built-in exception handler doesn't apply CORS middleware to 500 responses. Browser DevTools showed a CORS error masking the real server error. Fixed with a global `@app.exception_handler(Exception)` that applies CORS headers before re-raising.

**Hidden file input in upload zone** — the drag-and-drop zone had a hidden `<input type="file">` and "or click to select" text. Removed — upload is drag-and-drop only, which is the intended interaction.
