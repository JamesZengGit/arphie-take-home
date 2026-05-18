# System Architecture & Workflow

## Overview
Document Q&A system migrated from align-knowledge (hardware team decision tracker).
User uploads documents → system chunks and stores → user asks questions → keyword search retrieves chunks → AI generates grounded answer.

## Component Map

```
frontend/                          backend/api/main.py
  src/app/page.tsx                   FastAPI app on :8000
  src/components/
    documents/
      DocumentUpload.tsx  ──drag+drop──▶  POST /api/upload
      DocumentList.tsx    ──delete──────▶  DELETE /api/documents/{id}
    chat/
      ChatMessage.tsx     ──question───▶  POST /api/chat
  src/lib/api.ts          ──fetch──────▶  http://localhost:8000
```

## Request Flow: Document Upload

```
User drops file on DocumentUpload
  → POST /api/upload (multipart form)
  → Save file to disk
  → Insert row into documents table
  → TwoTierOrchestrator.process_document()
      → chunk document by paragraphs/sentences
      → extract entities (spaCy: people, topics, dates, file_refs)
      → insert chunks into document_chunks table
  → WebSocket /ws/status/{doc_id} pushes progress to frontend
  → DocumentList refreshes
```

## Request Flow: Chat Query

```
User types question in chat
  → POST /api/chat {message: "Who is James?"}
  → simple_document_search(query, limit=5)
      → extract keywords from query (filter stopwords, min 3 chars)
      → SQL: SELECT chunk_text FROM document_chunks WHERE chunk_text ILIKE $kw1 OR ILIKE $kw2 ...
      → returns list of {chunk_text, filename, entities, page_number, ...}
  → ai_generate_response(query, search_results)
      → build context from top chunks (capped at 3000 chars)
      → POST to OpenAI gpt-4o-mini
      → system prompt: "Answer using ONLY the provided excerpts"
      → returns answer string
  → Return ChatResponse {response, sources, stats, search_strategy}
```

## Request Flow: Delete Document

```
User clicks delete button in DocumentList
  → DELETE /api/documents/{external_document_id}
  → Lookup integer PK from external_document_id
  → DELETE FROM document_chunks WHERE document_id = int_id
  → DELETE FROM documents WHERE document_id = int_id
  → Frontend calls loadDocuments() to refresh list
```

## Database Schema

```sql
documents
  document_id           SERIAL PRIMARY KEY
  external_document_id  TEXT UNIQUE          -- exposed to frontend as "document_id"
  filename              TEXT
  file_path             TEXT
  content_type          TEXT
  processing_status     TEXT
  total_chunks          INT
  processed_chunks      INT

document_chunks
  chunk_id              SERIAL PRIMARY KEY
  document_id           INT REFERENCES documents
  chunk_index           INT
  chunk_text            TEXT
  page_number           INT
  section_header        TEXT
  entities              JSONB                -- {people, topics, dates, file_refs}
  embedding             VECTOR              -- not yet used in search
  search_vector         TSVECTOR           -- not yet used in search
  embedding_status      TEXT
  entity_extraction_status TEXT
```

## Key Files

| File | Role |
|------|------|
| `backend/api/main.py` | All API endpoints, search logic, AI generation, CORS |
| `backend/two_tier_orchestrator.py` | Document processing pipeline (chunking, entity extraction) |
| `backend/hybrid_retrieval.py` | Not yet active — placeholder for embedding-based search |
| `backend/redis_context_buffer.py` | From align-knowledge — context injection (not yet adapted) |
| `frontend/src/app/page.tsx` | Main React component, tab routing, state management |
| `frontend/src/components/documents/DocumentUpload.tsx` | Drag-drop upload zone |
| `frontend/src/components/documents/DocumentList.tsx` | Shows uploaded docs with delete button |
| `frontend/src/lib/api.ts` | Typed fetch wrapper for all backend calls |
| `evaluate_system.py` | RAGAs evaluation pipeline using ragas-wikiqa benchmark |

## What align-knowledge2 Has vs Lacks vs align-knowledge

| Feature | align-knowledge | align-knowledge2 |
|---------|----------------|-----------------|
| Document ingestion (PDF, MD, TXT) | ❌ | ✅ |
| Keyword search | ❌ | ✅ ILIKE OR conditions |
| AI Q&A responses | ❌ | ✅ gpt-4o-mini |
| Entity extraction (spaCy) | ✅ | ✅ same code kept |
| Redis context buffer (2hr TTL) | ✅ | ❌ not adapted |
| Entity overlap scoring (≥1.0 threshold) | ✅ | ❌ not adapted |
| Context injection into responses | ✅ | ❌ not adapted |
| Conversation continuity across queries | ✅ | ❌ not implemented |
| Gap detection (missing stakeholders) | ✅ | ❌ not adapted |
| Semantic/embedding search (pgvector) | ✅ 768-dim | ❌ schema exists, not wired |
| Personalized dashboard per user | ✅ | ❌ not adapted |
| RAGAs evaluation | ❌ | ✅ ragas-wikiqa benchmark |
| Document delete | ❌ | ✅ |
| Real-time upload status (WebSocket) | ❌ | ✅ |

See development/migration_source.md for full source system details and adaptation map.

## Environment Dependencies

```
PostgreSQL :5432  database=docqa
Redis      :6379  (imported but not actively used in search path)
OpenAI API key   read from /home/username/projects/align-knowledge/.env
Backend    :8000
Frontend   :3000
```

## Search Strategy: Why Keyword ILIKE
Chosen over embedding-based search because:
1. No embedding infrastructure needed (no vector DB, no embedding API calls at ingest)
2. Fully explainable — can show exactly what keywords matched
3. Sufficient for structured documents (resumes, reports, notes)
4. Embedding column exists in schema (vector) — can be activated later without schema changes

Weakness: No semantic matching. "automobile" won't find "car". Acceptable for 3-hour scope.
