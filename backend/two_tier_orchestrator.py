"""
Two-Tier Document Orchestrator
Bridges Redis live buffer + SQL persistent storage with atomic document Q&A processing
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import asdict

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logging.warning("asyncpg not available, SQL operations will fail")

from redis_context_buffer import RedisContextBuffer, LiveContextMessage
from pipelines.entity_extractor import DocumentEntityExtractor
from hybrid_retrieval import HybridRetrieval
from context_aware_responder import CachedContextResponder
from document_entities import DocumentExtractedEntities, DocumentContextMatcher

logger = logging.getLogger(__name__)

class TwoTierOrchestrator:
    """
    Orchestrates real-time context flow between Redis + SQL for document Q&A

    Core workflow:
    1. Query arrives → Entity extraction (~200ms)
    2. Atomic write: Redis buffer + SQL conversation history
    3. Context injection on subsequent queries
    4. Gap detection when information gaps found
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        postgres_url: str = "postgresql://postgres:postgres@localhost:5432/docqa",
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None
    ):
        # Components
        self.redis_buffer = RedisContextBuffer(redis_url)
        self.entity_extractor = DocumentEntityExtractor(postgres_url)
        self.hybrid_retriever = HybridRetrieval(postgres_url)
        self.context_responder = CachedContextResponder(anthropic_api_key, openai_api_key)
        self.context_matcher = DocumentContextMatcher()

        # Database
        self.postgres_url = postgres_url
        self.db_pool: Optional[asyncpg.Pool] = None

        # Performance tracking
        self.stats = {
            "messages_processed": 0,
            "context_injections": 0,
            "gaps_created": 0,
            "avg_processing_time_ms": 0.0,
            "redis_failures": 0,
            "sql_failures": 0
        }

    async def initialize(self):
        """Initialize Redis and PostgreSQL connections"""
        try:
            # Initialize Redis
            await self.redis_buffer.connect()

            # Initialize PostgreSQL pool
            if ASYNCPG_AVAILABLE:
                self.db_pool = await asyncpg.create_pool(
                    self.postgres_url,
                    min_size=2,
                    max_size=10,
                    command_timeout=30
                )
                logger.info("✅ Connected to PostgreSQL")
            else:
                logger.warning("⚠️  PostgreSQL unavailable - SQL operations disabled")

            logger.info("🚀 Two-tier orchestrator initialized")

        except Exception as e:
            logger.error(f"❌ Failed to initialize orchestrator: {e}")
            raise

    async def shutdown(self):
        """Cleanup connections"""
        await self.redis_buffer.disconnect()
        if self.db_pool:
            await self.db_pool.close()
        logger.info("🔌 Two-tier orchestrator shutdown complete")

    async def process_incoming_query(
        self,
        query_id: str,
        document_scope: str,
        user_id: str,
        query_text: str,
        timestamp: Optional[datetime] = None
    ) -> Dict:
        """
        Process incoming document query through two-tier pipeline

        Returns: {
            "conversation_created": bool,
            "context_injected": bool,
            "gap_created": bool,
            "processing_time_ms": float,
            "response": Optional[str]
        }
        """
        start_time = time.time()
        timestamp = timestamp or datetime.now()

        try:
            # Step 1: Extract entities from query (~200ms)
            logger.debug(f"🔍 Extracting entities from query {query_id}")
            entities_dict = await self.entity_extractor.extract_entities(query_text)

            # Convert to compatible format
            start_entity_time = time.time()
            entities = DocumentExtractedEntities.from_document_entities(
                entities_dict,
                extraction_time_ms=(time.time() - start_entity_time) * 1000
            )

            # Step 2: Track conversation for context (skip DB record for now)
            conversation_id = query_id if self._is_conversation_worthy(entities, query_text) else None

            # Step 3: Add to Redis buffer (with conversation_id if created)
            context_message = LiveContextMessage(
                message_id=query_id,
                user_id=user_id,
                text=query_text,
                entities=entities_dict,  # people, dates, topics, file_refs
                conversation_id=conversation_id,
                timestamp=timestamp.isoformat(),
                document_scope=document_scope
            )

            redis_success = await self.redis_buffer.add_message(document_scope, context_message)
            if not redis_success:
                self.stats["redis_failures"] += 1

            # Step 4: Check for context injection opportunity
            context_result = await self._check_context_injection(
                document_scope, entities, user_id, query_id, query_text
            )

            # Update stats
            processing_time = (time.time() - start_time) * 1000
            self.stats["messages_processed"] += 1
            self.stats["avg_processing_time_ms"] = (
                (self.stats["avg_processing_time_ms"] * (self.stats["messages_processed"] - 1) +
                 processing_time) / self.stats["messages_processed"]
            )

            if context_result.get("context_injected"):
                self.stats["context_injections"] += 1

            if context_result.get("gap_created"):
                self.stats["gaps_created"] += 1

            return {
                "conversation_created": bool(conversation_id),
                "conversation_id": conversation_id,
                "entities_extracted": len(entities.reqs) + len(entities.components) + len(entities.users_mentioned),
                "extraction_time_ms": entities.extraction_time_ms,
                "processing_time_ms": processing_time,
                **context_result
            }

        except Exception as e:
            logger.error(f"Failed to process query {query_id}: {e}")
            return {
                "conversation_created": False,
                "context_injected": False,
                "gap_created": False,
                "processing_time_ms": (time.time() - start_time) * 1000,
                "error": str(e)
            }

    def _is_conversation_worthy(self, entities: DocumentExtractedEntities, query_text: str) -> bool:
        """
        Determine if query represents a meaningful conversation to track

        Criteria:
        - Contains people/file references
        - Has topics mentioned
        - Contains question keywords
        - Has sufficient entity content
        """
        # File references or people mentioned are good conversation indicators
        if entities.reqs or entities.users_mentioned:
            return True

        # Multiple topics + question keywords
        question_keywords = [
            'what', 'how', 'why', 'where', 'when', 'who',
            'explain', 'describe', 'tell', 'show', 'find'
        ]

        has_question_keyword = any(
            keyword in query_text.lower() for keyword in question_keywords
        )

        if len(entities.components) >= 1 and has_question_keyword:
            return True

        # Simple heuristic: queries with entities are worth tracking
        total_entities = len(entities.reqs) + len(entities.components) + len(entities.users_mentioned)
        if total_entities >= 2:
            return True

        return False


    async def _check_context_injection(
        self,
        document_scope: str,
        b_entities: DocumentExtractedEntities,
        user_id: str,
        query_id: str,
        query_text: str = ""
    ) -> Dict:
        """
        Check if context should be injected based on entity overlap
        Create gaps and generate responses when overlap detected
        """
        try:
            # Get recent context from Redis buffer
            context_messages = await self.redis_buffer.get_recent_context(
                document_scope, max_messages=30, max_age_minutes=120
            )

            if not context_messages:
                return {"context_injected": False, "gap_created": False}

            # Extract entities from context messages
            buffer_entities = []
            for msg in context_messages:
                # Convert dict to DocumentExtractedEntities
                entities_dict = msg.entities
                entities_obj = DocumentExtractedEntities.from_document_entities(
                    entities_dict,
                    extraction_time_ms=0
                )
                buffer_entities.append(entities_obj)

            # Check for context injection
            should_inject, confidence, score = self.context_matcher.should_inject_context(
                b_entities, buffer_entities, confidence_threshold='medium'
            )

            if not should_inject:
                return {"context_injected": False, "gap_created": False}

            # Find matching context messages
            matching_contexts = []
            for msg in context_messages:
                msg_entities_dict = msg.entities
                msg_entities = DocumentExtractedEntities.from_document_entities(
                    msg_entities_dict,
                    extraction_time_ms=0
                )

                msg_confidence, msg_score = self.context_matcher.calculate_overlap_score(
                    b_entities, [msg_entities]
                )

                if msg_confidence in ['high', 'medium']:
                    matching_contexts.append({
                        'message': msg,
                        'confidence': msg_confidence,
                        'score': msg_score
                    })

            # Create gap if missing stakeholder detected
            gap_created = False
            if matching_contexts:
                gap_id = await self._create_gap_if_needed(
                    b_entities, matching_contexts, user_id
                )
                gap_created = bool(gap_id)

            # Generate context-aware response using LLM
            response_obj = await self.context_responder.generate_response(
                query_text,    # user_query
                b_entities,    # user_entities
                matching_contexts,
                user_id,
                gap_created,
                gap_id if gap_created else None
            )
            response = response_obj.response_text

            return {
                "context_injected": True,
                "gap_created": gap_created,
                "confidence": confidence,
                "score": score,
                "matching_contexts_count": len(matching_contexts),
                "response": response
            }

        except Exception as e:
            logger.error(f"Context injection check failed: {e}")
            return {"context_injected": False, "gap_created": False, "error": str(e)}

    async def _create_gap_if_needed(
        self,
        b_entities: DocumentExtractedEntities,
        matching_contexts: List[Dict],
        user_id: str
    ) -> Optional[str]:
        """
        Create gap record if missing stakeholder detected
        Gap: User should have been aware of related document content
        """
        if not self.db_pool:
            return None

        try:
            # Check if user was mentioned in any matching context
            user_was_mentioned = any(
                f"@{user_id}" in ctx['message'].entities.get('users_mentioned', [])
                for ctx in matching_contexts
            )

            if user_was_mentioned:
                return None  # User was already included

            # Generate gap description with context
            gap_id = await self._generate_gap_id()
            description = self._generate_gap_description(
                b_entities, matching_contexts, user_id
            )

            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO information_gaps (
                        gap_id, type, severity, description,
                        missing_topics, suggested_documents
                    ) VALUES ($1, 'missing_information', 'info', $2, $3, $4)
                """,
                    gap_id,
                    description,
                    [t for t in b_entities.components],
                    []
                )

                # Write gap_details rows
                # 1. context — why this gap was detected
                overlapping_topics = list({
                    c for ctx in matching_contexts
                    for c in ctx['message'].entities.get('components', [])
                    if c in b_entities.components
                })
                overlapping_reqs = list({
                    r for ctx in matching_contexts
                    for r in ctx['message'].entities.get('reqs', [])
                    if r in b_entities.reqs
                })
                await conn.execute("""
                    INSERT INTO gap_details (gap_id, detail_type, detail)
                    VALUES ($1, 'context', $2)
                """, gap_id, json.dumps({
                    "source": "orchestrator",
                    "overlapping_topics": overlapping_topics,
                    "overlapping_reqs": overlapping_reqs,
                    "matching_message_count": len(matching_contexts),
                }))

                # 2. stakeholder — the user who should have been included
                await conn.execute("""
                    INSERT INTO gap_details (gap_id, detail_type, detail)
                    VALUES ($1, 'stakeholder', $2)
                """, gap_id, json.dumps({
                    "user_id": user_id,
                    "role": "notified",
                }))

                # 3. relationships — link to other gaps that share overlapping components
                if overlapping_topics:
                    related = await conn.fetch("""
                        SELECT DISTINCT g.gap_id FROM information_gaps g
                        JOIN gap_details gd ON gd.gap_id = g.gap_id
                        WHERE gd.detail_type = 'context'
                          AND gd.detail->'overlapping_topics' ?| $1::text[]
                          AND g.gap_id != $2
                        LIMIT 5
                    """, overlapping_topics, gap_id)

                    for row in related:
                        target_gap_id = row["gap_id"]
                        await conn.execute("""
                            INSERT INTO gap_details (gap_id, detail_type, detail)
                            VALUES ($1, 'relationship', $2)
                        """, gap_id, json.dumps({
                            "target_gap_id": target_gap_id,
                            "relationship_type": "related_to",
                        }))

                logger.info(f"⚠️  Created gap {gap_id} for missing stakeholder {user_id} "
                            f"(topics={overlapping_topics})")
                return gap_id

        except Exception as e:
            logger.error(f"Failed to create gap: {e}")
            return None

    def _generate_gap_description(
        self,
        b_entities: DocumentExtractedEntities,
        matching_contexts: List[Dict],
        user_id: str
    ) -> str:
        """Generate descriptive gap text with context"""
        overlapping_topics = set()
        overlapping_reqs = set()

        for ctx in matching_contexts:
            msg_entities = ctx['message'].entities
            overlapping_topics.update(
                set(b_entities.components) & set(msg_entities.get('components', []))
            )
            overlapping_reqs.update(
                set(b_entities.reqs) & set(msg_entities.get('reqs', []))
            )

        topics_str = ', '.join(overlapping_topics)
        reqs_str = ', '.join(overlapping_reqs)

        description_parts = []
        if overlapping_reqs:
            description_parts.append(f"File references {reqs_str} mentioned")
        if overlapping_topics:
            description_parts.append(f"Topics {topics_str} discussed")

        context_info = ' and '.join(description_parts)

        return (f"User {user_id} mentioned {context_info} that were previously "
                f"discussed without their involvement. Consider including them "
                f"for future document queries.")

    async def _generate_gap_id(self) -> str:
        """Generate unique gap ID"""
        if not self.db_pool:
            return f"gap_{int(time.time())}"

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT COALESCE(MAX(CAST(gap_id AS INTEGER)), 0) + 1 FROM information_gaps"
                )
                return str(result)
        except Exception:
            return f"gap_{int(time.time())}"

    async def _generate_context_response(
        self,
        b_entities: DocumentExtractedEntities,
        matching_contexts: List[Dict],
        user_id: str
    ) -> str:
        """
        Generate context-aware response for user
        This would integrate with LLM for full responses
        """
        if not matching_contexts:
            return "No relevant context found."

        # For now, return structured context summary
        # In production, this would feed into Sonnet for natural language response
        context_summary = []

        for ctx in matching_contexts:
            msg = ctx['message']
            context_summary.append(
                f"Related discussion by {msg.user_id}: {msg.text[:100]}..."
            )

        overlapping_topics = set()
        for ctx in matching_contexts:
            msg_entities = ctx['message'].entities
            overlapping_topics.update(
                set(b_entities.components) & set(msg_entities.get('components', []))
            )

        response = (
            f"Found {len(matching_contexts)} related discussions about "
            f"{', '.join(overlapping_topics)}. "
            f"Context: {' | '.join(context_summary[:2])}"
        )

        return response

    async def get_stats(self) -> Dict:
        """Get orchestrator performance statistics"""
        redis_stats = await self.redis_buffer.get_channel_stats("document-qa")  # Example

        return {
            **self.stats,
            "redis_connected": bool(self.redis_buffer.redis_client),
            "postgres_connected": bool(self.db_pool),
            "sample_redis_stats": redis_stats
        }

    async def process_document_upload(self, file_content: bytes, filename: str) -> Dict:
        """Process uploaded document and start analysis"""
        if not self.db_pool:
            raise RuntimeError("Database not connected")

        try:
            external_document_id = str(uuid.uuid4())

            # Save file to disk so DocumentProcessor can read it
            upload_dir = "/tmp/documents"
            os.makedirs(upload_dir, exist_ok=True)
            file_path = f"{upload_dir}/{external_document_id}_{filename}"
            with open(file_path, "wb") as f:
                f.write(file_content)

            # Run the real pipeline: chunk + entity extract + store
            from backend.pipelines.document_processor import DocumentProcessor
            processor = DocumentProcessor(self.postgres_url)
            await processor.init_db_pool()
            await processor.process_document(file_path, external_document_id=external_document_id)

            # Fetch actual chunk count written by pipeline
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT d.document_id, COUNT(dc.chunk_id) as chunk_count
                    FROM documents d
                    LEFT JOIN document_chunks dc ON dc.document_id = d.document_id
                    WHERE d.external_document_id = $1
                    GROUP BY d.document_id
                """, external_document_id)
                chunk_count = row['chunk_count'] if row else 0

                await conn.execute("""
                    UPDATE documents
                    SET processing_status = 'completed',
                        total_chunks = $1,
                        processed_chunks = $1
                    WHERE external_document_id = $2
                """, chunk_count, external_document_id)

            return {
                "document_id": external_document_id,
                "filename": filename,
                "status": "completed",
                "message": f"Document uploaded and processed successfully ({chunk_count} chunks)"
            }

        except Exception as e:
            logger.error(f"Document upload failed: {e}")
            raise RuntimeError(f"Document processing failed: {str(e)}")

    async def get_all_documents(self) -> List[Dict]:
        """Get all uploaded documents with their status"""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT external_document_id, filename, content_type, created_at,
                           processing_status, total_chunks, processed_chunks
                    FROM documents
                    WHERE external_document_id IS NOT NULL
                    ORDER BY created_at DESC
                """)

                documents = []
                for row in rows:
                    documents.append({
                        "document_id": row['external_document_id'],
                        "filename": row['filename'],
                        "content_type": row['content_type'],
                        "upload_timestamp": row['created_at'].isoformat(),
                        "processing_status": row['processing_status'] or 'pending',
                        "total_chunks": row['total_chunks'] or 0,
                        "processed_chunks": row['processed_chunks'] or 0
                    })

                return documents

        except Exception as e:
            logger.error(f"Failed to get documents: {e}")
            return []

    async def get_processing_status(self, document_id: str) -> Optional[Dict]:
        """Get processing status for a specific document"""
        if not self.db_pool:
            return None

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT external_document_id, processing_status, total_chunks, processed_chunks,
                           filename, created_at
                    FROM documents
                    WHERE external_document_id = $1
                """, document_id)

                if not row:
                    return None

                processing_status = row['processing_status'] or 'pending'
                total_chunks = row['total_chunks'] or 1
                processed_chunks = row['processed_chunks'] or 0

                return {
                    "document_id": row['external_document_id'],
                    "status": processing_status,
                    "progress": int((processed_chunks / max(total_chunks, 1)) * 100),
                    "processing_stage": "completed" if processing_status == 'completed' else "processing",
                    "processed_chunks": processed_chunks,
                    "total_chunks": total_chunks,
                    "filename": row['filename']
                }

        except Exception as e:
            logger.error(f"Failed to get document status: {e}")
            return None

# Context manager for easy usage
class TwoTierManager:
    """Context manager for two-tier orchestrator"""

    def __init__(self, **kwargs):
        self.orchestrator = TwoTierOrchestrator(**kwargs)

    async def __aenter__(self):
        await self.orchestrator.initialize()
        return self.orchestrator

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.orchestrator.shutdown()

# Testing and example usage
if __name__ == "__main__":
    import asyncio

    async def test_two_tier_flow():
        """Test complete two-tier workflow"""
        async with TwoTierManager() as orchestrator:
            # Simulate Document Analyst posts about project update
            result_a = await orchestrator.process_incoming_query(
                query_id="query_001",
                document_scope="project-docs",
                user_id="alice",
                query_text="The project specification has been updated with new requirements for renewable energy integration"
            )

            print("Document Analyst query result:")
            print(json.dumps(result_a, indent=2))

            # Wait a bit (simulate time passing)
            await asyncio.sleep(1)

            # Simulate User B asks about energy 5 minutes later
            result_b = await orchestrator.process_incoming_query(
                query_id="query_002",
                document_scope="project-docs",
                user_id="bob",
                query_text="What are the current renewable energy integration requirements for the project?"
            )

            print("\nUser B query result:")
            print(json.dumps(result_b, indent=2))

            # Get orchestrator stats
            stats = await orchestrator.get_stats()
            print(f"\nOrchestrator stats:")
            print(json.dumps(stats, indent=2))

    # Run test
    asyncio.run(test_two_tier_flow())