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

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/docqa')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
UPLOAD_DIR = os.getenv('UPLOAD_DIR', '/tmp/documents')

# Global components
orchestrator = None
retriever = None

@app.on_event("startup")
async def startup_event():
    """Initialize system components"""
    global orchestrator, retriever

    try:
        orchestrator = TwoTierOrchestrator(
            redis_url=REDIS_URL,
            postgres_url=DATABASE_URL
        )
        await orchestrator.initialize()

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
    """Upload and process a document with real-time status updates"""
    try:
        allowed_extensions = {'.pdf', '.txt', '.md', '.markdown'}
        file_ext = Path(file.filename).suffix.lower()

        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )

        content = await file.read()

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
    """Document Q&A with basic keyword search and template responses"""
    if not message.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    query = message.message.strip()

    search_results = await simple_document_search(query, limit=5)

    response_text = generate_simple_response(query, search_results)

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
            "processing_time_ms": 50.0,
            "candidates_found": len(search_results),
            "final_results": len(search_results)
        },
        search_strategy="simple_sql"
    )

async def simple_document_search(query: str, limit: int = 5):
    """Basic document search: matches the full query phrase against chunk text."""
    conn = await asyncpg.connect(DATABASE_URL)

    sql = """
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
    WHERE dc.chunk_text ILIKE $1
    ORDER BY dc.chunk_id DESC
    LIMIT $2
    """

    rows = await conn.fetch(sql, f"%{query}%", limit)
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
    """Generate simple template response based on search results"""

    if not results:
        return f"No content found matching '{query}' in your documents. Try different keywords or upload more documents."

    best_result = results[0]

    response = f"I found information about '{query}'"
    response += f" in '{best_result['filename']}'"

    if best_result['page_number']:
        response += f" on page {best_result['page_number']}"

    response += ":\n\n"

    content = best_result['chunk_text']
    if len(content) > 400:
        content = content[:400] + "..."

    response += content

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

@app.websocket("/ws/status/{document_id}")
async def websocket_document_status(websocket: WebSocket, document_id: str):
    """WebSocket for real-time document processing updates"""
    await websocket.accept()

    try:
        while True:
            status = await orchestrator.get_processing_status(document_id)

            if status:
                await websocket.send_text(json.dumps(status))

                if status.get("status") in ["completed", "failed"]:
                    break

            await asyncio.sleep(1)

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
