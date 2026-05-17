"""
Document Embedding Pipeline
Adapted from align-knowledge for document chunks
Generates embeddings for document chunks using sentence-transformers
"""

import asyncio
import asyncpg
import numpy as np
import os
import logging
from typing import List, Tuple
from datetime import datetime
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentEmbeddingPipeline:
    """
    Batch embedding pipeline for document chunks
    Processes pending chunks and generates 768-dimensional embeddings
    """

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        self.model_name = model_name
        self.model = None
        self.db_pool = None

    async def init_model(self):
        """Load sentence-transformers model"""
        logger.info(f"Loading sentence-transformers model: {self.model_name}")
        self.model = SentenceTransformer(self.model_name)
        logger.info("Model loaded successfully")

    async def init_db_pool(self, database_url: str):
        """Initialize PostgreSQL connection pool"""
        logger.info(f"Connecting to database: {database_url}")
        self.db_pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info("Database connection pool created")

    async def get_pending_chunks(self, batch_size: int = 100) -> List[Tuple[int, str]]:
        """
        Fetch document chunks with pending embedding status
        Returns list of (chunk_id, chunk_text) tuples
        """
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT chunk_id, chunk_text
                FROM document_chunks
                WHERE embedding_status = 'pending'
                ORDER BY created_at ASC
                LIMIT $1
            """
            rows = await conn.fetch(query, batch_size)
            return [(row['chunk_id'], row['chunk_text']) for row in rows]

    async def generate_embeddings(self, texts: List[str]) -> np.ndarray:
        """
        Generate embeddings for batch of texts
        Returns numpy array of shape (n_texts, 768)
        """
        if not self.model:
            await self.init_model()

        logger.info(f"Generating embeddings for {len(texts)} texts")
        start_time = datetime.now()

        # Generate embeddings
        embeddings = self.model.encode(
            texts,
            batch_size=32,  # Process in mini-batches for memory efficiency
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True  # Normalize for cosine similarity
        )

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Generated {len(embeddings)} embeddings in {duration:.2f}s ({duration/len(texts):.3f}s per text)")

        return embeddings

    async def update_embeddings(self, chunk_ids: List[int], embeddings: np.ndarray) -> int:
        """
        Update database with generated embeddings
        Returns number of updated records
        """
        async with self.db_pool.acquire() as conn:
            updated_count = 0

            # Start transaction for batch update
            async with conn.transaction():
                for chunk_id, embedding in zip(chunk_ids, embeddings):
                    try:
                        # Convert numpy array to list for JSON storage
                        embedding_list = embedding.tolist()

                        await conn.execute("""
                            UPDATE document_chunks
                            SET embedding = $1::vector,
                                embedding_status = 'embedded',
                                updated_at = NOW()
                            WHERE chunk_id = $2
                        """, embedding_list, chunk_id)

                        updated_count += 1

                    except Exception as e:
                        logger.error(f"Failed to update chunk {chunk_id}: {e}")
                        # Mark as failed for retry
                        await conn.execute("""
                            UPDATE document_chunks
                            SET embedding_status = 'failed',
                                updated_at = NOW()
                            WHERE chunk_id = $1
                        """, chunk_id)

            logger.info(f"Updated {updated_count} chunks with embeddings")
            return updated_count

    async def create_vector_index(self):
        """
        Create pgvector index after embeddings are populated
        This enables fast similarity search
        """
        async with self.db_pool.acquire() as conn:
            # Check if we have enough embeddings to justify index creation
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM document_chunks WHERE embedding_status = 'embedded'
            """)

            if count < 50:  # Lower threshold for document chunks
                logger.info(f"Only {count} embeddings available, skipping index creation")
                return

            # Create ivfflat index for vector similarity
            logger.info("Creating pgvector index for fast similarity search...")

            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chunks_embedding
                    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 50);
                """)
                logger.info("pgvector index created successfully")

                # Analyze table for query optimization
                await conn.execute("ANALYZE document_chunks;")

            except Exception as e:
                logger.error(f"Failed to create vector index: {e}")

    async def batch_process(self, batch_size: int = 100) -> int:
        """
        Main batch processing loop
        Processes all pending chunks in batches
        """
        if not self.db_pool:
            raise Exception("Database pool not initialized")

        total_processed = 0
        batch_count = 0

        while True:
            # Get pending chunks
            pending = await self.get_pending_chunks(batch_size)
            if not pending:
                logger.info("No more pending chunks to process")
                break

            batch_count += 1
            logger.info(f"Processing batch {batch_count}: {len(pending)} chunks")

            # Extract texts and IDs
            chunk_ids = [item[0] for item in pending]
            texts = [item[1] for item in pending]

            # Generate embeddings
            embeddings = await self.generate_embeddings(texts)

            # Update database
            updated = await self.update_embeddings(chunk_ids, embeddings)
            total_processed += updated

            logger.info(f"Batch {batch_count} complete: {updated}/{len(pending)} updated")

        # Create vector index if we processed data
        if total_processed > 0:
            await self.create_vector_index()

        logger.info(f"Batch processing complete: {total_processed} total chunks processed")
        return total_processed

    async def get_embedding_stats(self) -> dict:
        """Get statistics about embedding status"""
        async with self.db_pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_chunks,
                    COUNT(*) FILTER (WHERE embedding_status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE embedding_status = 'embedded') as embedded,
                    COUNT(*) FILTER (WHERE embedding_status = 'failed') as failed,
                    AVG(length(chunk_text)) as avg_text_length
                FROM document_chunks
            """)

            return dict(stats)

    async def close(self):
        """Clean up resources"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("Database connection pool closed")