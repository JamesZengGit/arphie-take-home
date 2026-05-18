# Mission Progress

## Mission
Migrate align-knowledge (hardware team AI decision tracker) → document Q&A web app.
User drops in mixed documents (PDF, Markdown, plain text), asks natural language questions, gets grounded AI answers.

## Milestone Tracker

### ✅ Session 1 (Previous) — Core System Fix & Enhancement
**Starting state**: Chat returning "I couldn't find any documents" for valid queries even when documents existed in DB.

| Milestone | Status | Notes |
|---|---|---|
| Expose real errors by removing fallbacks | Done | Revealed CORS error and phrase-search bug |
| Fix CORS on backend errors | Done | Global exception handler with CORS headers |
| Fix search logic | Done | Keyword extraction + OR ILIKE instead of full-phrase |
| AI-powered responses via OpenAI | Done | gpt-4o-mini, reads key from align-knowledge/.env |
| Remove file input from Document Library | Done | Was exposing hidden `<input type="file">` |
| Remove Upload section from Document Library tab | Done | Upload only in Upload Documents tab |
| Add delete document function | Done | DELETE endpoint + frontend button with loading state |
| Fix frontend TypeScript errors | Done | Removed legacy components from align-knowledge migration |

### ✅ Session 2 (Current) — RAGAs Evaluation System
**Starting state**: No evaluation harness, no way to prove system reliability to customers.

| Milestone | Status | Notes |
|---|---|---|
| Research evaluation approach | Done | Chose RAGAs as mature industry standard |
| Plan end-to-end evaluation logic | Done | Rejected hardcoded queries, rejected custom GPT generation |
| Delete fake evaluation scripts | Done | demo_evaluation.py was measuring "did API respond", not quality |
| Implement real RAGAs pipeline | Done | Uses ragas-wikiqa HuggingFace benchmark |
| Run end-to-end evaluation | Done | Got real scores, verified exit code 0 |
| Document evaluation system | Done | development/evaluation.md |

## Verified Working (End-to-End Tested)
- Backend API starts on port 8000
- Frontend starts on port 3000
- Document upload (drag-and-drop PDF, MD, TXT)
- Chat with documents returns AI-grounded answers
- Document delete via frontend button
- RAGAs evaluation: `python evaluate_system.py --n 10 --save`

## Currently Missing / Not Implemented
- Context injection pipeline from align-knowledge (Redis buffer, entity scoring)
- Conversation continuity between queries (session memory)
- Gap detection and relationship mapping
- Semantic/embedding-based search (current is keyword ILIKE SQL)
- Entity Explorer UI panel (entities extracted and stored in DB but not surfaced)
- `/api/stats` endpoint data not shown in frontend

## Next Priority (with 4 more hours)
Ordered by impact vs implementation cost. Full source system specs in development/migration_source.md.

1. **Surface entity data in frontend** — already in DB (`document_chunks.entities` JSONB with people, topics, dates), just needs UI panel. Zero backend changes.
2. **Conversation continuity** — adapt Redis buffer from align-knowledge: store last N query-result pairs, score entity overlap (threshold ≥ 1.0) on each new query, inject prior context. Source scoring algorithm documented in migration_source.md.
3. **Entity overlap scoring for retrieval ranking** — current search returns chunks with any keyword match at equal weight. Apply align-knowledge's scoring (exact entity match 2.0, topic match 0.8) to rank chunks better.
4. **Semantic/embedding search** — pgvector column already in schema, embeddings pipeline already in `backend/hybrid_retrieval.py` from migration. Wire it up to replace or supplement ILIKE search.
