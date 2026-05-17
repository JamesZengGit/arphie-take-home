"""
Document Processing Pipeline
Handles PDF, Markdown, and text file ingestion with chunking
"""

import os
import asyncio
import asyncpg
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import re

# Document processing libraries
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logging.warning("pdfplumber not available, PDF processing disabled")

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    logging.warning("markdown not available, MD processing will use plain text")

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """
    Processes documents and stores chunks with metadata
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.db_pool = None
        # Chunking parameters
        self.chunk_size = 500  # words per chunk
        self.chunk_overlap = 50  # word overlap between chunks

    async def init_db_pool(self):
        """Initialize PostgreSQL connection pool"""
        if not self.db_pool:
            self.db_pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=30
            )

    async def process_document(self, file_path: str, external_document_id: str = None) -> int:
        """
        Process a document and return document_id
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Document not found: {file_path}")

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        # Detect content type
        content_type = self._detect_content_type(file_path)

        # Extract text based on content type
        if content_type == 'pdf':
            text_chunks = await self._process_pdf(file_path)
        elif content_type == 'markdown':
            text_chunks = await self._process_markdown(file_path)
        else:  # text
            text_chunks = await self._process_text(file_path)

        # Store document in database
        document_id = await self._store_document(filename, file_path, content_type, file_size, text_chunks, external_document_id)

        logger.info(f"Processed {filename}: {len(text_chunks)} chunks created")
        return document_id

    def _detect_content_type(self, file_path: str) -> str:
        """Detect document content type from extension"""
        ext = Path(file_path).suffix.lower()
        if ext == '.pdf':
            return 'pdf'
        elif ext in ['.md', '.markdown']:
            return 'markdown'
        else:
            return 'text'

    async def _process_pdf(self, file_path: str) -> List[Dict]:
        """Extract text from PDF with page information"""
        if not PDF_AVAILABLE:
            raise ImportError("pdfplumber not installed, cannot process PDF")

        chunks = []

        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    # Clean and chunk the page text
                    cleaned_text = self._clean_text(text)
                    page_chunks = self._create_chunks(cleaned_text)

                    for i, chunk_text in enumerate(page_chunks):
                        chunks.append({
                            'text': chunk_text,
                            'page_number': page_num,
                            'section_header': None,
                            'chunk_index': len(chunks)
                        })

        return chunks

    async def _process_markdown(self, file_path: str) -> List[Dict]:
        """Extract text from Markdown with section information"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        chunks = []
        current_section = None

        # Split by headers to preserve document structure
        lines = content.split('\n')
        current_text = []

        for line in lines:
            # Check for markdown headers
            if line.startswith('#'):
                # Save previous section
                if current_text:
                    text = '\n'.join(current_text)
                    cleaned_text = self._clean_text(text)
                    section_chunks = self._create_chunks(cleaned_text)

                    for chunk_text in section_chunks:
                        chunks.append({
                            'text': chunk_text,
                            'page_number': None,
                            'section_header': current_section,
                            'chunk_index': len(chunks)
                        })
                    current_text = []

                # Extract header text
                current_section = re.sub(r'^#+\s*', '', line).strip()
            else:
                current_text.append(line)

        # Process remaining text
        if current_text:
            text = '\n'.join(current_text)
            cleaned_text = self._clean_text(text)
            section_chunks = self._create_chunks(cleaned_text)

            for chunk_text in section_chunks:
                chunks.append({
                    'text': chunk_text,
                    'page_number': None,
                    'section_header': current_section,
                    'chunk_index': len(chunks)
                })

        return chunks

    async def _process_text(self, file_path: str) -> List[Dict]:
        """Extract text from plain text file"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        cleaned_text = self._clean_text(content)
        text_chunks = self._create_chunks(cleaned_text)

        chunks = []
        for i, chunk_text in enumerate(text_chunks):
            chunks.append({
                'text': chunk_text,
                'page_number': None,
                'section_header': None,
                'chunk_index': i
            })

        return chunks

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove empty lines
        text = re.sub(r'\n\s*\n', '\n', text)
        return text.strip()

    def _create_chunks(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []

        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i + self.chunk_size]
            if len(chunk_words) < 10:  # Skip very small chunks
                continue
            chunks.append(' '.join(chunk_words))

        return chunks

    async def _store_document(self, filename: str, file_path: str, content_type: str,
                            file_size: int, chunks: List[Dict], external_document_id: str = None) -> int:
        """Store document and chunks in database"""
        if not self.db_pool:
            await self.init_db_pool()

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                # Insert document
                document_id = await conn.fetchval("""
                    INSERT INTO documents (external_document_id, filename, file_path, content_type, file_size, total_chunks)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING document_id
                """, external_document_id, filename, file_path, content_type, file_size, len(chunks))

                # Insert chunks
                for chunk in chunks:
                    await conn.execute("""
                        INSERT INTO document_chunks
                        (document_id, chunk_index, chunk_text, page_number, section_header,
                         entity_extraction_status, embedding_status)
                        VALUES ($1, $2, $3, $4, $5, 'pending', 'pending')
                    """, document_id, chunk['chunk_index'], chunk['text'],
                        chunk['page_number'], chunk['section_header'])

                return document_id

    async def get_document_stats(self) -> Dict:
        """Get processing statistics"""
        if not self.db_pool:
            await self.init_db_pool()

        async with self.db_pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_documents,
                    COUNT(*) FILTER (WHERE content_type = 'pdf') as pdf_count,
                    COUNT(*) FILTER (WHERE content_type = 'markdown') as markdown_count,
                    COUNT(*) FILTER (WHERE content_type = 'text') as text_count,
                    SUM(total_chunks) as total_chunks,
                    AVG(total_chunks) as avg_chunks_per_doc
                FROM documents
            """)

            chunk_stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_chunks,
                    COUNT(*) FILTER (WHERE entity_extraction_status = 'pending') as pending_entities,
                    COUNT(*) FILTER (WHERE embedding_status = 'pending') as pending_embeddings
                FROM document_chunks
            """)

            return {
                "documents": dict(stats),
                "chunks": dict(chunk_stats)
            }

    async def close(self):
        """Clean up resources"""
        if self.db_pool:
            await self.db_pool.close()