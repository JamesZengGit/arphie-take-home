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
