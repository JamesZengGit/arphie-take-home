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
