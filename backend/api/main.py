"""
Document Q&A FastAPI Server
Intelligent document processing with real-time status and progressive search
"""

import os
import asyncio
import logging
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg
import json
import openai

# Import from parent directories
import sys
sys.path.append(str(Path(__file__).parent.parent))

from two_tier_orchestrator import TwoTierOrchestrator
from hybrid_retrieval import HybridRetrieval
from redis_context_buffer import RedisContextBuffer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Request/Response models
class ChatMessage(BaseModel):
    message: str
    entity_filters: Optional[List[str]] = None

class ChatResponse(BaseModel):
    response: str
    sources: List[dict]
    stats: dict
    search_strategy: str

class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    message: str

# Initialize FastAPI app
app = FastAPI(
    title="Intelligent Document Q&A System",
    version="2.0.0",
    description="Real-time document processing with progressive search capabilities"
)

# Add CORS middleware to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CORS_ORIGINS = ["http://localhost:3000", "http://localhost:3001"]

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in CORS_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=headers,
    )

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/docqa')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
UPLOAD_DIR = os.getenv('UPLOAD_DIR', '/tmp/documents')

# Load OpenAI key from align-knowledge .env
def _load_openai_key() -> str:
    env_path = Path(__file__).parent.parent.parent.parent / "align-knowledge" / ".env"
    try:
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.getenv("OPENAI_API_KEY", "")

OPENAI_API_KEY = _load_openai_key()
_openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Global components
orchestrator = None
retriever = None

@app.on_event("startup")
async def startup_event():
    """Initialize system components"""
    global orchestrator, retriever

    try:
        # Initialize orchestrator
        orchestrator = TwoTierOrchestrator(
            redis_url=REDIS_URL,
            postgres_url=DATABASE_URL
        )
        await orchestrator.initialize()

        # Initialize retriever
        retriever = HybridRetrieval()
        await retriever.init_model()
        await retriever.init_db_pool(DATABASE_URL)

        logger.info("✅ Intelligent Document Q&A system initialized")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources"""
    global orchestrator, retriever

    try:
        if orchestrator:
            await orchestrator.shutdown()
        if retriever:
            await retriever.close()

        logger.info("✅ System shutdown complete")

    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")

@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    Upload and process a document with real-time status updates
    """
    try:
        # Validate file type
        allowed_extensions = {'.pdf', '.txt', '.md', '.markdown'}
        file_ext = Path(file.filename).suffix.lower()

        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )

        # Read file content
        content = await file.read()

        # Process with orchestrator
        result = await orchestrator.process_document_upload(
            file_content=content,
            filename=file.filename
        )

        return UploadResponse(**result)

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat", response_model=ChatResponse)
async def chat_with_documents(message: ChatMessage):
    """
    Document Q&A with hybrid retrieval and intelligent response generation
    """
    if not message.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    query = message.message.strip()
    entity_filters = message.entity_filters or []

    # Simple document search using SQL (for now)
    search_results = await simple_document_search(query, limit=5)

    # AI-powered answer from retrieved chunks
    response_text = await ai_generate_response(query, search_results)

    # Process through orchestrator for context tracking (async)
    orchestrator_result = await orchestrator.process_incoming_query(
        query_id=f"query_{int(asyncio.get_event_loop().time())}",
        document_scope="all",
        user_id="user",
        query_text=query
    )

    return ChatResponse(
        response=response_text,
        sources=search_results,
        stats={
            "processing_time_ms": 50.0,  # placeholder
            "candidates_found": len(search_results),
            "final_results": len(search_results)
        },
        search_strategy="simple_sql"
    )

async def generate_intelligent_response(query: str, results: List, stats) -> str:
    """Generate contextual response based on search results and strategy"""

    if not results:
        return "I couldn't find relevant information about that in your documents."

    # Analyze search strategy for response
    strategy_context = {
        "full_smart": "Using advanced semantic understanding",
        "keyword_entity": "Based on keyword and entity matching",
        "keyword_only": "Using keyword matching",
        "fallback": "Using basic search"
    }

    best_result = results[0]
    strategy_desc = strategy_context.get(stats.query_type, "Using available search methods")

    # Build contextual response
    response = f"{strategy_desc}, I found relevant information"

    # Add source context
    if best_result.page_number:
        response += f" from '{best_result.filename}' on page {best_result.page_number}"
    else:
        response += f" in '{best_result.filename}'"

    if best_result.section_header:
        response += f" (section: {best_result.section_header})"

    response += ":\n\n"

    # Add content with intelligent truncation
    content = best_result.chunk_text
    if len(content) > 400:
        # Try to break at sentence boundary
        sentences = content.split('.')
        truncated = ""
        for sentence in sentences:
            if len(truncated + sentence) < 400:
                truncated += sentence + "."
            else:
                break
        content = truncated

    response += content

    # Add additional context if multiple sources
    if len(results) > 1:
        other_sources = [r.filename for r in results[1:3]]
        unique_sources = list(set(other_sources))
        if unique_sources:
            response += f"\n\nI also found related information in: {', '.join(unique_sources)}"

    # Add search performance note
    response += f"\n\n*(Search completed in {stats.total_time_ms:.0f}ms using {stats.query_type} strategy)*"

    return response

async def ai_generate_response(query: str, results: list) -> str:
    """Use OpenAI to generate a natural-language answer from retrieved chunks."""
    if not _openai_client:
        return generate_simple_response(query, results)

    if not results:
        return f"No content found matching '{query}' in your documents. Try different keywords or upload more documents."

    # Build context from top chunks (cap at ~3000 chars to stay within token budget)
    context_parts = []
    char_budget = 3000
    for r in results:
        snippet = r['chunk_text'][:800]
        source = f"[{r['filename']}]"
        entry = f"{source}\n{snippet}"
        if char_budget - len(entry) < 0:
            break
        context_parts.append(entry)
        char_budget -= len(entry)

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = (
        "You are a document Q&A assistant. Answer the user's question using ONLY "
        "the provided document excerpts. Be concise and direct. If the answer is in "
        "the excerpts, state it clearly. If it is not, say so honestly."
    )
    user_prompt = f"Question: {query}\n\nDocument excerpts:\n{context}"

    completion = await _openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=400,
        temperature=0.2,
    )
    return completion.choices[0].message.content.strip()

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "i", "you", "he", "she", "it", "we", "they", "what", "which", "who",
    "this", "that", "these", "those", "in", "on", "at", "to", "for",
    "of", "with", "about", "by", "from", "as", "into", "through",
    "and", "or", "but", "if", "then", "so", "me", "my", "your", "its",
    "tell", "give", "show", "find", "get", "make", "how", "when", "where",
    "summarize", "summary", "describe", "explain", "list", "main", "key",
}

async def simple_document_search(query: str, limit: int = 5):
    """Keyword-level document search: splits query into meaningful terms and matches any."""
    # Extract meaningful keywords
    words = [w.strip(".,?!;:\"'()") for w in query.lower().split()]
    keywords = [w for w in words if w and len(w) > 2 and w not in STOPWORDS]

    # Fall back to the full query if all words were stopwords
    if not keywords:
        keywords = [query]

    conn = await asyncpg.connect(DATABASE_URL)

    # Build OR conditions — one ILIKE per keyword
    conditions = " OR ".join(f"dc.chunk_text ILIKE ${i+1}" for i in range(len(keywords)))
    params = [f"%{kw}%" for kw in keywords]
    params.append(limit)

    sql = f"""
    SELECT
        dc.chunk_id,
        dc.chunk_text,
        d.filename,
        d.content_type,
        dc.entities,
        dc.page_number,
        dc.section_header,
        0.8 as similarity_score
    FROM document_chunks dc
    JOIN documents d ON dc.document_id = d.document_id
    WHERE {conditions}
    ORDER BY dc.chunk_id DESC
    LIMIT ${len(keywords) + 1}
    """

    rows = await conn.fetch(sql, *params)
    await conn.close()

    results = []
    for row in rows:
        results.append({
            'chunk_id': row['chunk_id'],
            'chunk_text': row['chunk_text'],
            'filename': row['filename'],
            'content_type': row['content_type'],
            'entities': row['entities'] or {},
            'page_number': row['page_number'],
            'section_header': row['section_header'],
            'similarity_score': row['similarity_score']
        })

    return results

def generate_simple_response(query: str, results) -> str:
    """Generate simple response based on search results"""

    if not results:
        return f"No content found matching '{query}' in your documents. Try different keywords or upload more documents."

    # Use the first result
    best_result = results[0]

    # Build simple response
    response = f"I found information about '{query}'"
    response += f" in '{best_result['filename']}'"

    if best_result['page_number']:
        response += f" on page {best_result['page_number']}"

    response += ":\n\n"

    # Add content (truncate if too long)
    content = best_result['chunk_text']
    if len(content) > 400:
        content = content[:400] + "..."

    response += content

    # Add info about additional results
    if len(results) > 1:
        response += f"\n\nI found {len(results)} relevant sections in your documents."

    return response

@app.get("/api/status/{document_id}")
async def get_document_status(document_id: str):
    """Get real-time processing status for a document"""
    try:
        status = await orchestrator.get_processing_status(document_id)

        if not status:
            raise HTTPException(status_code=404, detail="Document not found")

        return status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents")
async def get_all_documents():
    """Get status of all documents"""
    try:
        documents = await orchestrator.get_all_documents()
        return {
            "documents": documents,
            "total": len(documents)
        }

    except Exception as e:
        logger.error(f"Get documents failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str):
    """Delete a document and all its chunks (document_id is external_document_id)"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        int_id = await conn.fetchval(
            "SELECT document_id FROM documents WHERE external_document_id = $1", document_id
        )
        if not int_id:
            raise HTTPException(status_code=404, detail="Document not found")

        await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", int_id)
        await conn.execute("DELETE FROM documents WHERE document_id = $1", int_id)
        return {"deleted": document_id}
    finally:
        await conn.close()

@app.websocket("/ws/status/{document_id}")
async def websocket_document_status(websocket: WebSocket, document_id: str):
    """WebSocket for real-time document processing updates"""
    await websocket.accept()

    try:
        while True:
            status = await orchestrator.get_processing_status(document_id)

            if status:
                await websocket.send_text(json.dumps(status))

                # Stop sending updates if processing is complete
                if status.get("status") in ["completed", "failed"]:
                    break

            await asyncio.sleep(1)  # Update every second

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()

@app.get("/api/stats")
async def get_system_stats():
    """Get comprehensive system statistics"""
    try:
        orchestrator_stats = await orchestrator.get_stats()

        return {
            "system": "Intelligent Document Q&A",
            "orchestrator": orchestrator_stats,
            "capabilities": {
                "real_time_processing": True,
                "progressive_search": True,
                "entity_extraction": True,
                "semantic_search": True,
                "full_text_search": True
            }
        }

    except Exception as e:
        logger.error(f"Stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/evaluate")
async def evaluate_system():
    """Run system evaluation and return reliability metrics"""
    try:
        # Import evaluation functions
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

        from demo_evaluation import SimpleEvaluator

        evaluator = SimpleEvaluator()
        results = await evaluator.run_demo_evaluation()

        # Return customer-focused metrics
        if "error" in results:
            return {"status": "error", "message": results["error"]}

        return {
            "status": "success",
            "success_rate": results["success_rate"],
            "content_rate": results["content_rate"],
            "total_queries": results["total_queries"],
            "successful_queries": results["successful_queries"],
            "evaluation_timestamp": results["timestamp"],
            "reliability_status": (
                "excellent" if results["success_rate"] >= 80 else
                "good" if results["success_rate"] >= 60 else
                "needs_improvement"
            )
        }
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        return {"status": "error", "message": f"Evaluation unavailable: {str(e)}"}

# Removed embedded HTML frontend - will be replaced with proper Next.js frontend

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)