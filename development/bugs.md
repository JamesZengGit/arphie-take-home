# Bug Encounters Log

## Bug 1 — Chat Returning "No Documents Found" Despite Documents Existing
**Session**: Previous (Session 1)
**Discovery**: User reported chat always returned fallback message even with uploaded documents.

**Investigation**:
- Direct DB query confirmed documents and chunks existed with searchable content
- curl test to API confirmed search was returning results correctly
- Disconnect was between API functionality and frontend behavior

**Root Cause**: Two separate bugs masked by fallback error handling:
1. CORS blocked the actual error from reaching the frontend
2. Search used full-phrase ILIKE (`%Summarize the main recommendations%`) which never matched any chunk

**Fix**:
- Removed all try-catch fallbacks to expose real errors first
- Then fixed both root causes separately (see Bugs 2 and 3)

**Lesson**: Fallbacks hide real bugs. Always expose errors before masking them.

---

## Bug 2 — CORS Error on Backend Exceptions
**Session**: Previous (Session 1)
**Discovery**: Browser console showed `Access-Control-Allow-Origin header is not present` only on error responses.

**Root Cause**: When FastAPI raised an unhandled exception, `ServerErrorMiddleware` handled it before `CORSMiddleware` could add headers. Error responses had no CORS headers, so browser blocked them.

**Fix**: Added global exception handler that explicitly adds CORS headers to all error responses:
```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in CORS_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(status_code=500, content={"detail": str(exc)}, headers=headers)
```

**File**: `backend/api/main.py`

---

## Bug 3 — Full-Phrase ILIKE Never Matched Chunks
**Session**: Previous (Session 1)
**Discovery**: After CORS fix, error revealed search returned zero results for natural language queries.

**Root Cause**: `simple_document_search()` used the entire query string as one ILIKE pattern:
```sql
WHERE chunk_text ILIKE '%Summarize the main recommendations%'
```
This required the exact phrase to appear verbatim in a chunk, which never happened.

**Fix**: Rewrote to extract meaningful keywords, build OR conditions:
```python
STOPWORDS = {"a", "an", "the", "is", "are", ...}
words = [w.strip(".,?!;:") for w in query.lower().split()]
keywords = [w for w in words if len(w) > 2 and w not in STOPWORDS]
conditions = " OR ".join(f"chunk_text ILIKE ${i+1}" for i in range(len(keywords)))
```

**File**: `backend/api/main.py` — `simple_document_search()` function

---

## Bug 4 — DELETE Endpoint Schema Mismatch
**Session**: Previous (Session 1)
**Discovery**: Delete button returned 422 error.

**Root Cause**: API exposes `external_document_id` as `document_id` in responses. The DELETE endpoint was trying to use it as the integer primary key directly.

**Fix**: Added lookup step — find integer PK from `external_document_id` first:
```python
int_id = await conn.fetchval(
    "SELECT document_id FROM documents WHERE external_document_id = $1", document_id
)
```

**File**: `backend/api/main.py` — `delete_document()` function

---

## Bug 5 — Frontend TypeScript Errors Preventing Compilation
**Session**: Previous (Session 1)
**Discovery**: User reported "frontend not running".

**Root Cause**: Legacy component directories from align-knowledge migration (`chat/`, `dashboard/`, `decisions/`, etc.) contained broken imports referencing files that didn't exist in align-knowledge2.

**Fix**: Removed unused legacy component directories and `mock-data.ts`. Frontend compiled cleanly after removal.

**Files removed**: Legacy component dirs under `frontend/src/components/`

---

## Bug 6 — RAGAs TestsetGenerator Rejected Short Chunks
**Session**: Current (Session 2)
**Discovery**: TestsetGenerator raised `ValueError: Documents appears to be too short (ie 100 tokens or less)`.

**Root Cause**: Our DB has few documents with small chunks (142–525 chars). Even after aggregating all chunks per document, content was insufficient for TestsetGenerator's knowledge graph construction.

**Decision**: Switch to ragas-wikiqa benchmark dataset from HuggingFace instead of generating from our own documents.

---

## Bug 7 — RAGAs 0.4.x API Incompatibility with Collections Metrics
**Session**: Current (Session 2)
**Discovery**: `Faithfulness(llm=LangchainLLMWrapper(...))` raised `ValueError: Collections metrics only support modern InstructorLLM`.

**Root Cause**: RAGAs 0.4.x has two parallel metric systems:
- `ragas.metrics.collections.*` — new system requiring `llm_factory()` (InstructorLLM)
- `ragas.metrics._faithfulness` etc. — legacy singletons compatible with `evaluate()` auto-injection

**Fix**: Import from private legacy modules:
```python
from ragas.metrics._faithfulness import faithfulness
from ragas.metrics._context_precision import context_precision
from ragas.metrics._context_recall import context_recall
```

---

## Bug 8 — `dict(EvaluationResult)` Raised KeyError: 0
**Session**: Current (Session 2)
**Discovery**: `return dict(result)` crashed after successful RAGAs evaluation.

**Root Cause**: `EvaluationResult.__getitem__` uses string keys (metric names). `dict()` passes integer keys (0, 1, 2...) when converting.

**Fix**: Use `.to_pandas()` and aggregate per column:
```python
df = result.to_pandas()
return {col: float(df[col].mean()) for col in ["faithfulness", "context_precision", "context_recall"] if col in df.columns}
```

---

## Bug 9 — answer_relevancy Metric Embedding API Conflict
**Session**: Current (Session 2)
**Discovery**: `AttributeError: 'OpenAIEmbeddings' object has no attribute 'embed_query'`

**Root Cause**: `answer_relevancy` metric from the legacy module expects LangChain embedding interface (`embed_query`), but the installed `langchain_openai.OpenAIEmbeddings` version had a different interface.

**Decision**: Drop `answer_relevancy` from metrics. The three remaining metrics (faithfulness, context_precision, context_recall) are LLM-only and cover the most critical reliability dimensions.
