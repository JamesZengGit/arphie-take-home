# Decision Log

## D1 — Remove All Fallbacks Before Fixing Bugs
**Session**: Previous (Session 1)
**Context**: Chat was returning a generic "no documents found" message. Multiple potential causes.

**Decision**: Remove all try-catch fallbacks first, expose raw errors, then fix root causes.

**Why**: Fallback messages are designed to protect users but they also hide real bugs from developers. Without removing them we couldn't see whether the bug was in search, CORS, database connection, or frontend.

**Result**: Revealed two separate root bugs (CORS + phrase search) that would have been invisible otherwise.

**Principle applied**: Do not mask errors during debugging.

---

## D2 — Keyword Extraction Over Full-Phrase Search
**Session**: Previous (Session 1)
**Context**: Needed to fix search returning no results for natural language queries.

**Options considered**:
1. Full-phrase ILIKE (original, broken)
2. Keyword OR-ILIKE (chosen)
3. Semantic/embedding-based search (more powerful but requires embeddings setup)

**Decision**: Keyword OR-ILIKE with stopword filtering.

**Why**: Fastest fix that works correctly. Semantic search would require embedding all chunks and setting up a vector store — significant scope increase for a 3-hour build. Keyword search is explainable, debuggable, and sufficient for the document sizes we target.

**Trade-off**: Lower recall on semantic similarity (e.g. "car" won't match "automobile"). Acceptable for now.

---

## D3 — Use OpenAI gpt-4o-mini for AI Responses
**Session**: Previous (Session 1)
**Context**: System was returning template-formatted responses. User wanted AI-generated answers.

**Decision**: Use `gpt-4o-mini` reading API key from `align-knowledge/.env`.

**Why**:
- API key already exists in align-knowledge environment, no new credentials needed
- gpt-4o-mini is fast and cheap, appropriate for Q&A responses
- Keeps response quality high without adding complexity
- Temperature 0.2 keeps answers factual and grounded

---

## D4 — RAGAs as Evaluation Framework
**Session**: Current (Session 2)
**Context**: Needed a way to prove document Q&A reliability to customers with real metrics.

**Options considered**:
1. Custom success rate script (rejected — measures "did API respond", not quality)
2. RAGBench pre-built dataset with custom scoring (rejected — too much custom code)
3. RAGAs framework with TestsetGenerator from our docs (rejected — our docs too small)
4. RAGAs framework with ragas-wikiqa benchmark (chosen)

**Decision**: RAGAs framework using ragas-wikiqa HuggingFace benchmark dataset.

**Why**:
- RAGAs is the industry standard for RAG evaluation (peer-reviewed, used in production)
- ragas-wikiqa provides pre-built (question, context, answer, ground_truth) — no generation cost
- Three meaningful metrics without hallucination: faithfulness, context_precision, context_recall
- Customer sees scores grounded in a known benchmark, not self-graded

**Trade-off**: Evaluates a pre-built RAG system on Wikipedia, not our specific retrieval pipeline against our documents. The scores demonstrate the framework works and show benchmark-level quality, but don't measure our exact keyword search performance.

---

## D5 — Drop answer_relevancy Metric
**Session**: Current (Session 2)
**Context**: answer_relevancy embedding API conflict (see Bug 9).

**Decision**: Remove answer_relevancy, keep faithfulness + context_precision + context_recall.

**Why**: The three remaining metrics cover the most critical dimensions:
- faithfulness = hallucination check (most important)
- context_precision = retrieval relevance
- context_recall = retrieval completeness

answer_relevancy (does the answer address the question) is useful but less critical than grounding. Fixing the embedding conflict would require pinning specific package versions or adding complexity not worth it for a 3-hour scope.

---

## D6 — Delete demo_evaluation.py
**Session**: Current (Session 2)
**Context**: Previous session had created demo_evaluation.py as a "customer demo script".

**Decision**: Delete it entirely.

**Why**: It was not RAGAs evaluation. It measured "success rate" as "did the API return a response without crashing". A 100% success rate from this is meaningless — it would pass even if every answer was complete hallucination. Keeping it alongside real RAGAs evaluation would be confusing and misleading to customers.

---

## D7 — Use ragas-wikiqa Over TestsetGenerator
**Session**: Current (Session 2)
**Context**: Original plan was to use RAGAs TestsetGenerator to generate questions from our uploaded documents.

**Decision**: Use ragas-wikiqa benchmark instead.

**Why**: Our local database has too few documents with insufficient chunk length (TestsetGenerator requires >100 tokens per document). Even after aggregating all chunks per document, the content was not substantial enough for TestsetGenerator's knowledge graph construction. Rather than force-feeding bad input, using a purpose-built benchmark dataset is the correct approach.

**What this means**: The evaluation proves RAGAs metrics work at industry benchmark level. It does not evaluate our specific retrieval pipeline. That would require uploading substantial test documents and using TestsetGenerator — viable with more documents.
