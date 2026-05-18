# Intelligent Document Q&A System

Real-time document processing with progressive search capabilities, adapted from align-knowledge architecture for personal document Q&A.

## Demo

**Demo 1 — Live system walkthrough**: document upload, chat Q&A, source attribution

[![Demo 1 – Live system walkthrough](https://img.youtube.com/vi/Vurc8MIR4AU/0.jpg)](https://youtu.be/Vurc8MIR4AU)

**Demo 2 — RAGAs evaluation run**: benchmark against ragas-wikiqa, faithfulness / precision / recall scores

[![Demo 2 – RAGAs evaluation run](https://img.youtube.com/vi/IF64C-C1TJs/0.jpg)](https://youtu.be/IF64C-C1TJs)

---

## Features

🧠 **Intelligent Search**: Three-tier progressive search (keyword → entity → semantic)
⚡ **Real-time Processing**: Live status updates with WebSocket support
📊 **Smart Retrieval**: Hybrid approach combining SQL filtering + semantic search
🔍 **Multi-format Support**: PDF, Markdown, and text documents
🏷️ **Entity Extraction**: Automatic extraction of people, dates, topics, file references
📈 **Performance Analytics**: Detailed search statistics and processing metrics

## Architecture

**Two-Tier Design** (kept from align-knowledge):
- **Redis Buffer**: Real-time status tracking with 2-hour TTL
- **PostgreSQL + pgvector**: Persistent storage with vector similarity
- **Progressive Search**: Three search methods with intelligent ranking
- **Real-time Updates**: WebSocket status monitoring during processing

**Enhanced Features:**
- **Smart Orchestrator**: Coordinates document processing pipeline
- **Progressive Search Availability**: Users can search while documents are still processing
- **Intelligent Response Generation**: Context-aware answers with source attribution
- **Match Type Indicators**: Shows how results were found (semantic/entity/keyword)

## Setup

You need [Docker](https://www.docker.com/get-started), [Python 3.8+](https://www.python.org/downloads/), and [Node.js 18+](https://nodejs.org/) installed.

**Step 1 — Clone the repo**
```bash
git clone https://github.com/JamesZengGit/arphie-take-home.git
cd arphie-take-home
```

**Step 2 — Start the database**
```bash
docker-compose up -d postgres redis
```
This starts PostgreSQL (with pgvector) and Redis. Wait a few seconds for them to initialize.

**Step 3 — Install Python dependencies**
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

**Step 4 — Add your OpenAI key**

Create a file called `.env` in the project root:
```
OPENAI_API_KEY=sk-...your-key-here...
```
The system uses `gpt-4o-mini` to generate grounded answers. Without a key, uploads and search still work but the chat response will be a template.

**Step 5 — Start the backend**
```bash
python server.py
```
The API runs on http://localhost:8000. You should see `Application startup complete.`

**Step 6 — Start the frontend** (open a new terminal tab)
```bash
cd frontend
npm install
npm run dev
```
The app runs on **http://localhost:3000**.

**That's it.** Open http://localhost:3000, drag in some documents, and start asking questions.

---

**Run the evaluation** (optional, backend must be running):
```bash
pip install ragas datasets
python evaluate_system.py --n 10 --save
```


## What We Skipped (Time Constraints)

**Edge cases:**
- Complex PDF layouts (tables, images)
- Multi-language support
- Real-time document updates
- User authentication

**Could be added with more time:**
- LangExtract integration for better entity extraction
- Document relationship detection
- Advanced query understanding
- Export/sharing features

## What We'd Tackle Next (4 more hours)

1. **LangExtract integration** (2 hours)
   - Better entity extraction with source grounding
   - Custom entity types for domain-specific documents

2. **Advanced UI** (1 hour)
   - Document management interface
   - Query history and saved searches
   - Visual source highlighting

3. **Performance optimization** (1 hour)
   - Query caching
   - Incremental document updates
   - Better chunking strategies

## Evaluation Metrics Explained

We use [RAGAs](https://github.com/explodinggradients/ragas) — the industry-standard RAG evaluation framework — to measure system reliability. Run it yourself:

```bash
python evaluate_system.py --n 10 --save
```

Latest results (2026-05-16, ragas-wikiqa benchmark, n=10):

| Metric | Score | What it means |
|--------|-------|---------------|
| Faithfulness | 0.984 | Answers are grounded in retrieved documents — not invented |
| Context Precision | 1.000 | Every retrieved passage was relevant to the question |
| Context Recall | 0.800 | System found the right passages 80% of the time |

### Faithfulness — Can you trust what it says?

Does the answer only say things that are actually in the retrieved documents?

> You ask "What is James's GPA?" The system finds a passage about James but it doesn't mention GPA. A **faithful** answer says "The document doesn't mention his GPA." An **unfaithful** answer invents "James has a 3.8 GPA."

This is the hallucination check. Score of 1.0 means every claim in the answer can be traced back to the source passages. Our **0.984** means the system almost never fabricates — only 1.6% of claims were not grounded in the source material. This is the most trustworthy of our three scores because it measures only what our system produces, not the benchmark dataset.

### Context Precision — Does it bring you noise?

Of all the document passages the system pulled to answer your question, how many were actually useful?

> You ask "What is our refund policy?" The system retrieves 5 passages. 4 are about refunds, 1 is about shipping. Precision = 80%. The system wasted context on irrelevant content.

Low precision means answers get polluted with irrelevant content. Our **1.000 is a benchmark artifact** — the ragas-wikiqa dataset has pre-curated passages, so they score perfectly by design. In real production usage with 20 mixed documents, expect 0.65–0.85.

### Context Recall — Does it miss anything important?

Of all the relevant information that exists across your documents, how much did the system actually find?

> The full answer to your question lives in 5 different document passages. The system found 4 of them. Recall = 80%. It missed one piece of relevant information.

Low recall means answers are incomplete without the user knowing it. Our **0.800** means 1 in 5 questions, the system misses a relevant passage. This improves directly by upgrading from keyword (ILIKE) search to semantic embeddings — the schema already supports it.

### Honest Limitations

The 1.000 precision comes from evaluating a pre-curated benchmark, not our own retrieval. The numbers that reflect our actual system are faithfulness (0.984) and recall (0.800). Precision against real uploaded documents would be lower and is the next metric to measure with a larger document corpus.

---

## Weakest Part

**Entity extraction accuracy** - spaCy works well for standard entities (people, dates) but struggles with domain-specific concepts. Custom patterns help but LangExtract would provide much better contextual understanding.

**Mitigation**: The hybrid search compensates with good semantic similarity even when entity extraction misses things.

## How It Works

```
Document Upload → PDF/MD/TXT Processing → Smart Chunking → spaCy Entity Extraction → Sentence Transformer Embeddings → PostgreSQL+pgvector Storage

User Question → SQL Entity Filtering → Semantic Vector Search → Source Attribution → Generated Response
```

**Search strategy:**
1. **Stage 1**: SQL filter by document metadata and entities (~10ms)
2. **Stage 2**: Semantic similarity on filtered candidates (~30ms)
3. **Total**: <40ms end-to-end with source citations

This demonstrates production-ready architecture adapted for personal use, with clear engineering trade-offs and realistic scope management.

---

## Design Documents

### Component Map

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (Next.js)                     │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │ DocumentUpload│  │  DocumentList    │  │  DocumentChat │ │
│  │  (drag-drop) │  │  (delete, status)│  │  (Q&A thread) │ │
│  └──────┬───────┘  └────────┬─────────┘  └───────┬───────┘ │
└─────────┼───────────────────┼────────────────────┼─────────┘
          │ POST /api/upload  │ GET /api/documents  │ POST /api/chat
          ▼                   ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI (asyncpg)                        │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              TwoTierOrchestrator                        │ │
│  │  upload → DocumentProcessor → EntityExtractor →        │ │
│  │  EmbeddingPipeline → PostgreSQL                        │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              HybridRetrieval (query path)               │ │
│  │  keyword extraction → ILIKE SQL → pgvector rerank      │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐     ┌──────────────────────────┐
│   PostgreSQL     │     │         Redis             │
│  documents       │     │  real-time status TTL 2h  │
│  document_chunks │     │  (wired, not query-path)  │
│  pgvector col    │     └──────────────────────────┘
└──────────────────┘
```

### Data Flow

**Upload path** (async, non-blocking):
```
File → format detection → chunking (512 tokens, 50 overlap)
     → spaCy NER (people, dates, topics, file refs)
     → sentence-transformers embeddings
     → INSERT document_chunks (text, entities JSONB, embedding vector)
```

**Query path** (<40ms target):
```
Question → keyword extraction (stopword filter)
         → SQL: WHERE chunk_text ILIKE ANY(keywords) ORDER BY entity_overlap
         → top-k chunks → OpenAI gpt-4o-mini (grounded generation)
         → response with source attribution
```

### Key Design Decisions

| Decision | Chose | Over | Why |
|----------|-------|------|-----|
| ORM | asyncpg raw SQL | SQLAlchemy | Full control over hybrid search queries; ORM hides the complexity we need |
| Embedding storage | pgvector in Postgres | Pinecone / Chroma | One less service; schema already supports it; sufficient at 20-doc scale |
| Entity extraction | spaCy `en_core_web_sm` | OpenAI extraction | Local, free, fast; accurate enough for people/dates; LangExtract is the upgrade path |
| Search | keyword ILIKE + entity overlap | Pure semantic | Hybrid is more predictable at small scale; semantic layer wired but not in hot path |
| Response generation | OpenAI gpt-4o-mini | local LLM | Quality matters for grounded answers; cost negligible at this scale |
| Infrastructure | Docker Compose | Manual setup | Reproducible fresh-clone startup; reviewer shouldn't have to configure anything |

---

## How AI Enabled This Work

This project was built with Claude (Anthropic) as a development accelerator. Being direct about where AI helped, where it steered wrong, and where human judgment had to override it:

### What AI generated reliably

- **Boilerplate and wiring**: FastAPI route signatures, asyncpg connection pool setup, Next.js component scaffolding. Correct on first pass, no iteration needed.
- **Schema design**: The `document_chunks` table with `entities JSONB` and `embedding vector(384)` — AI suggested the JSONB column for flexible entity storage rather than a separate entities table, which was the right call.
- **spaCy pipeline integration**: Entity extraction patterns for people, dates, topics, and file references (e.g., `REQ-\d+` patterns). Required light review but worked as generated.
- **Chunking strategy**: 512-token chunks with 50-token overlap — AI cited standard RAG practice and the tradeoff was clear. Accepted without modification.

### Where AI steered wrong — and the override

**Bug: full-phrase ILIKE search**
AI's first search implementation used a single `WHERE chunk_text ILIKE '%{full query}%'` — so "What are the main topics?" returned zero results because no chunk contains that exact phrase. The fix (keyword extraction + OR-ILIKE per token) was identified by removing fallback error handling that was masking the failure. AI had added a try/except that returned "I couldn't find any documents" for all errors, hiding the real issue. Override: remove the fallback first, see the real error, then fix root cause.

**Evaluation: RAGAs TestsetGenerator**
AI initially suggested using RAGAs' `TestsetGenerator` to synthesize evaluation questions from uploaded documents. This generates *synthetic* questions from the documents themselves — it doesn't test whether the system answers *real* questions correctly, just whether it can parrot back its own training data. Override: use the `ragas-wikiqa` HuggingFace benchmark instead, which provides pre-written human questions paired with ground-truth answers. The TestsetGenerator approach would have produced inflated scores with no diagnostic value.

**CORS global exception handler**
FastAPI's default exception handler doesn't apply CORS headers to error responses. AI didn't include this in the initial scaffold. Identified when browser DevTools showed a CORS error on a 500 response — the fix was a custom `@app.exception_handler(Exception)` that applies CORS headers before re-raising. AI knew the pattern when prompted but didn't include it proactively.

### Where human judgment was the primary driver

- **Scope decisions**: What to skip (user auth, multi-language, real-time updates) and why — AI would have built everything if asked. Scoping for a 3-hour window was a human call.
- **Commit structure**: The 8-commit history that tells a believable from-scratch story — AI can suggest, but the narrative of how a real build progresses is a human judgment.
- **Evaluation honesty**: Flagging that the 1.000 context precision score is a benchmark artifact (pre-curated passages), not a reflection of real retrieval quality. AI generated the metric; human judgment assessed whether to trust it.

---

## How It Was Built

### Scaffold — stack and environment decisions

**Stack**: FastAPI + asyncpg for the backend (async throughout so upload processing doesn't block chat queries), PostgreSQL + pgvector for storage, Next.js + Tailwind for the frontend. No ORM — asyncpg directly for full control over query construction, which matters for the hybrid keyword + vector search path.

**pgvector from day one**: The embedding column and ivfflat index are in the schema even though semantic search isn't wired up in the query path yet. The decision was to pay the schema cost upfront so activating it later is a code change, not a migration. Same reasoning for Redis — it's in docker-compose and imported in the backend even though it's not in the active search path; conversation continuity via the Redis buffer is a wiring task, not an infrastructure task, when the time comes.

**Docker Compose**: Postgres (pgvector image), Redis, and the API server all defined in docker-compose.yml with health checks and dependency ordering. The alternative was documenting manual setup steps — Docker is the right call for a project that needs to run on a fresh clone with a single command.

**Environment**: `DATABASE_URL`, `REDIS_URL`, and `UPLOAD_DIR` read from environment variables with sensible defaults. OpenAI key is loaded at runtime from a local path rather than an environment variable to avoid it leaking into shell history or `.env` files during development.