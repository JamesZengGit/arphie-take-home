"""
Hybrid Retrieval System for Knowledge Aligner
Combines SQL filtering with semantic vector search for <40ms performance
Two-stage approach: SQL filter → semantic search on candidates
"""

import asyncio
import asyncpg
import numpy as np
import time
import logging
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

@dataclass
class DocumentRetrievalResult:
    """Single document chunk result with similarity score"""
    chunk_id: int
    chunk_text: str
    filename: str
    content_type: str
    entities: Dict[str, List[str]]
    page_number: Optional[int]
    section_header: Optional[str]
    similarity_score: float
    embedding: Optional[List[float]] = None

@dataclass
class RetrievalStats:
    """Performance statistics for retrieval"""
    total_time_ms: float
    sql_filter_time_ms: float
    semantic_search_time_ms: float
    candidates_found: int
    final_results: int
    query_type: str  # 'sql_only', 'semantic_only', 'hybrid'

class HybridRetrieval:
    """
    High-performance hybrid retrieval system
    Stage 1: SQL filtering (components, time, author) - ~10ms
    Stage 2: Semantic similarity on candidates - ~30ms
    Total target: <40ms for 10K decisions
    """

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        self.model_name = model_name
        self.model = None
        self.db_pool = None

    async def init_model(self):
        """Load sentence-transformers model for query encoding"""
        if not self.model:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)

    async def init_db_pool(self, database_url: str):
        """Initialize PostgreSQL connection pool"""
        if not self.db_pool:
            self.db_pool = await asyncpg.create_pool(
                database_url,
                min_size=5,
                max_size=20,
                command_timeout=10  # Fast timeout for performance
            )

    async def sql_filter(self,
                        user_topics: List[str],
                        time_filter_days: int = 30,
                        author_filter: Optional[str] = None,
                        decision_type: Optional[str] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """
        Stage 1: Fast SQL filtering based on structured criteria
        Target: <10ms for 10K decisions
        """
        start_time = time.perf_counter()

        async with self.db_pool.acquire() as conn:
            # Build dynamic query based on filters
            conditions = ["embedding_status = 'embedded'"]
            params = []
            param_count = 0

            # Component overlap filter (most important)
            if user_topics:
                param_count += 1
                conditions.append(f"dc.entities ? ${param_count}")
                params.append(user_topics)

            # Time filter
            param_count += 1
            conditions.append(f"dc.created_at >= ${param_count}")
            params.append(datetime.now() - timedelta(days=time_filter_days))

            # Author filter
            if author_filter:
                param_count += 1
                conditions.append(f"author_user_id = ${param_count}")
                params.append(author_filter)

            # Decision type filter
            if decision_type:
                param_count += 1
                conditions.append(f"decision_type = ${param_count}")
                params.append(decision_type)

            # Limit parameter
            param_count += 1
            params.append(limit)

            query = f"""
                SELECT dc.chunk_id, dc.chunk_text, d.filename, d.content_type,
                       dc.entities, dc.page_number, dc.section_header,
                       dc.embedding, 1.0 as similarity_score
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.document_id
                WHERE {' AND '.join(conditions)}
                ORDER BY dc.created_at DESC
                LIMIT ${param_count}
            """

            rows = await conn.fetch(query, *params)

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(f"SQL filter: {len(rows)} candidates in {duration_ms:.2f}ms")

        return [dict(row) for row in rows]

    async def semantic_search(self,
                             query_text: str,
                             candidates: List[Dict[str, Any]],
                             limit: int = 20) -> List[DocumentRetrievalResult]:
        """
        Stage 2: Semantic similarity search on SQL-filtered candidates
        Target: <30ms for 100 candidates
        """
        if not candidates:
            return []

        start_time = time.perf_counter()

        # Initialize model if needed
        if not self.model:
            await self.init_model()

        # Encode query text
        query_embedding = self.model.encode([query_text], normalize_embeddings=True)[0]

        # Calculate similarities
        results = []
        for candidate in candidates:
            # Extract embedding from database
            if candidate['embedding']:
                decision_embedding = np.array(candidate['embedding'])

                # Calculate cosine similarity
                similarity = np.dot(query_embedding, decision_embedding)
            else:
                # Fallback for missing embeddings
                similarity = 0.0

            result = DocumentRetrievalResult(
                chunk_id=candidate['chunk_id'],
                chunk_text=candidate['chunk_text'],
                filename=candidate['filename'],
                content_type=candidate['content_type'],
                entities=candidate['entities'] or {},
                page_number=candidate['page_number'],
                section_header=candidate['section_header'],
                similarity_score=similarity,
                embedding=candidate['embedding']
            )
            results.append(result)

        # Sort by similarity and limit results
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        final_results = results[:limit]

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(f"Semantic search: {len(final_results)} results in {duration_ms:.2f}ms")

        return final_results

    async def hybrid_search(self,
                           user_id: str,
                           query_text: str = "",
                           user_topics: List[str] = None,
                           time_filter_days: int = 30,
                           limit: int = 20) -> Tuple[List[DocumentRetrievalResult], RetrievalStats]:
        """
        Main hybrid search function
        Combines SQL filtering with semantic search for optimal performance
        """
        total_start = time.perf_counter()

        # Get user components if not provided
        if user_topics is None:
            user_topics = await self.get_user_document_preferences(user_id)

        # Stage 1: SQL filtering
        sql_start = time.perf_counter()
        candidates = await self.sql_filter(
            user_topics=user_topics,
            time_filter_days=time_filter_days,
            limit=min(100, limit * 5)  # Get more candidates than needed
        )
        sql_time_ms = (time.perf_counter() - sql_start) * 1000

        # Determine search strategy
        if not query_text.strip():
            # Pure SQL filtering (component-based)
            results = []
            for candidate in candidates[:limit]:
                result = DocumentRetrievalResult(
                    chunk_id=candidate['chunk_id'],
                    chunk_text=candidate['chunk_text'],
                    filename=candidate['filename'],
                    content_type=candidate['content_type'],
                    entities=candidate['entities'] or {},
                    page_number=candidate['page_number'],
                    section_header=candidate['section_header'],
                    similarity_score=candidate['similarity_score'] or 0.0
                )
                results.append(result)

            semantic_time_ms = 0
            query_type = 'sql_only'

        else:
            # Stage 2: Semantic search on candidates
            semantic_start = time.perf_counter()
            results = await self.semantic_search(query_text, candidates, limit)
            semantic_time_ms = (time.perf_counter() - semantic_start) * 1000
            query_type = 'hybrid'

        total_time_ms = (time.perf_counter() - total_start) * 1000

        # Create performance stats
        stats = RetrievalStats(
            total_time_ms=total_time_ms,
            sql_filter_time_ms=sql_time_ms,
            semantic_search_time_ms=semantic_time_ms,
            candidates_found=len(candidates),
            final_results=len(results),
            query_type=query_type
        )

        logger.info(f"Hybrid search: {len(results)} results in {total_time_ms:.1f}ms ({query_type})")

        return results, stats

    async def pure_semantic_search(self,
                                  query_text: str,
                                  limit: int = 20,
                                  similarity_threshold: float = 0.5) -> List[DocumentRetrievalResult]:
        """
        Pure semantic search using pgvector similarity
        For comparison with hybrid approach
        """
        if not self.model:
            await self.init_model()

        start_time = time.perf_counter()

        # Encode query
        query_embedding = self.model.encode([query_text], normalize_embeddings=True)[0]
        embedding_list = query_embedding.tolist()

        async with self.db_pool.acquire() as conn:
            # Use pgvector similarity operator
            query = """
                SELECT dc.chunk_id, dc.chunk_text, d.filename, d.content_type,
                       dc.entities, dc.page_number, dc.section_header,
                       dc.embedding <=> $1 as similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.document_id
                WHERE embedding_status = 'embedded'
                  AND embedding <=> $1 < $2
                ORDER BY embedding <=> $1
                LIMIT $3
            """

            rows = await conn.fetch(query, embedding_list, 1.0 - similarity_threshold, limit)

        # Convert to results
        results = []
        for row in rows:
            result = DocumentRetrievalResult(
                chunk_id=row['chunk_id'],
                chunk_text=row['chunk_text'],
                filename=row['filename'],
                content_type=row['content_type'],
                entities=row['entities'] or {},
                page_number=row['page_number'],
                section_header=row['section_header'],
                similarity_score=1.0 - row['similarity']  # Convert distance to similarity
            )
            results.append(result)

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Pure semantic search: {len(results)} results in {duration_ms:.1f}ms")

        return results

    async def get_user_document_preferences(self, user_id: str) -> List[str]:
        """Get user's document access patterns and preferences"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT preferred_document_types
                FROM user_document_preferences
                WHERE user_id = $1
            """, user_id)

            return row['preferred_document_types'] if row else []

    async def benchmark_performance(self,
                                   test_queries: List[str],
                                   user_id: str = 'alice') -> Dict[str, Any]:
        """
        Benchmark different retrieval strategies
        Compare SQL-only, hybrid, and pure semantic performance
        """
        logger.info(f"Benchmarking with {len(test_queries)} queries")

        user_topics = await self.get_user_document_preferences(user_id)
        results = {
            'sql_only': [],
            'hybrid': [],
            'pure_semantic': []
        }

        for query in test_queries:
            # SQL-only (component filtering)
            start = time.perf_counter()
            sql_candidates = await self.sql_filter(user_topics, limit=20)
            sql_time = (time.perf_counter() - start) * 1000
            results['sql_only'].append(sql_time)

            # Hybrid search
            _, hybrid_stats = await self.hybrid_search(user_id, query)
            results['hybrid'].append(hybrid_stats.total_time_ms)

            # Pure semantic search
            start = time.perf_counter()
            await self.pure_semantic_search(query)
            semantic_time = (time.perf_counter() - start) * 1000
            results['pure_semantic'].append(semantic_time)

        # Calculate statistics
        benchmark_results = {}
        for method, times in results.items():
            benchmark_results[method] = {
                'avg_time_ms': np.mean(times),
                'p50_time_ms': np.percentile(times, 50),
                'p95_time_ms': np.percentile(times, 95),
                'p99_time_ms': np.percentile(times, 99),
                'min_time_ms': np.min(times),
                'max_time_ms': np.max(times)
            }

        return benchmark_results

    async def close(self):
        """Clean up resources"""
        if self.db_pool:
            await self.db_pool.close()

# CLI for testing and benchmarking
async def main():
    import argparse
    import os

    parser = argparse.ArgumentParser(description='Hybrid Retrieval System')
    parser.add_argument('--query', type=str, help='Test query')
    parser.add_argument('--user-id', type=str, default='alice', help='User ID for filtering')
    parser.add_argument('--benchmark', action='store_true', help='Run performance benchmark')
    parser.add_argument('--limit', type=int, default=20, help='Number of results')

    args = parser.parse_args()

    # Initialize retrieval system
    database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/knowledge_aligner')
    retriever = HybridRetrieval()

    try:
        await retriever.init_db_pool(database_url)

        if args.benchmark:
            # Run benchmark with test queries
            test_queries = [
                "renewable energy integration requirements",
                "sustainability reporting standards",
                "environmental impact assessment",
                "green technology implementation",
                "carbon footprint analysis"
            ]

            results = await retriever.benchmark_performance(test_queries, args.user_id)

            print("Performance Benchmark Results:")
            for method, stats in results.items():
                print(f"\n{method.upper()}:")
                print(f"  Average: {stats['avg_time_ms']:.1f}ms")
                print(f"  P95: {stats['p95_time_ms']:.1f}ms")
                print(f"  P99: {stats['p99_time_ms']:.1f}ms")

        elif args.query:
            # Single query test
            results, stats = await retriever.hybrid_search(
                user_id=args.user_id,
                query_text=args.query,
                limit=args.limit
            )

            print(f"Query: '{args.query}'")
            print(f"Performance: {stats.total_time_ms:.1f}ms total ({stats.query_type})")
            print(f"  SQL Filter: {stats.sql_filter_time_ms:.1f}ms")
            print(f"  Semantic: {stats.semantic_search_time_ms:.1f}ms")
            print(f"Results: {len(results)}")

            for i, result in enumerate(results[:5]):
                print(f"\n{i+1}. [{result.chunk_id}] {result.filename}")
                print(f"   Similarity: {result.similarity_score:.3f}")
                print(f"   Entities: {result.entities}")
                print(f"   Text: {result.chunk_text[:100]}...")

        else:
            print("Use --query 'text' for search or --benchmark for performance testing")

    finally:
        await retriever.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())