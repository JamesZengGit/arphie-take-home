"""
Entity Extraction for Documents
Using spaCy for fast, reliable extraction with custom patterns for documents
"""

import asyncio
import asyncpg
import logging
import re
from typing import List, Dict, Any, Optional
import json

# spaCy for entity extraction
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    logging.warning("spaCy not available, using regex-only extraction")

logger = logging.getLogger(__name__)

class DocumentEntityExtractor:
    """
    Extract entities from document chunks using spaCy + custom patterns
    Entities: people, dates, topics, file_references
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.db_pool = None
        self.nlp = None

    async def init_spacy(self):
        """Initialize spaCy model"""
        if not SPACY_AVAILABLE:
            logger.warning("spaCy not available, using regex-only extraction")
            return

        try:
            self.nlp = spacy.load("en_core_web_sm")
            logger.info("spaCy model loaded successfully")
        except OSError:
            logger.warning("spaCy model 'en_core_web_sm' not found, using regex-only")
            self.nlp = None

    async def init_db_pool(self):
        """Initialize PostgreSQL connection pool"""
        if not self.db_pool:
            self.db_pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=30
            )

    async def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract entities from text using spaCy + custom patterns
        Returns dict with entity types as keys and lists of entities as values
        """
        entities = {
            'people': [],
            'dates': [],
            'topics': [],
            'file_refs': []
        }

        # Custom pattern extraction (always available)
        entities.update(self._extract_with_patterns(text))

        # spaCy extraction (if available)
        if self.nlp:
            spacy_entities = self._extract_with_spacy(text)
            # Merge results, deduplicating
            for entity_type, entity_list in spacy_entities.items():
                entities[entity_type].extend(entity_list)
                entities[entity_type] = list(set(entities[entity_type]))

        return entities

    def _extract_with_patterns(self, text: str) -> Dict[str, List[str]]:
        """Extract entities using regex patterns"""
        entities = {
            'people': [],
            'dates': [],
            'topics': [],
            'file_refs': []
        }

        # File references (various formats)
        file_patterns = [
            r'\b[\w\-]+\.(?:pdf|doc|docx|txt|md|xlsx|ppt|pptx)\b',  # filename.ext
            r'\bpage\s+\d+\b',  # page 5
            r'\bsection\s+[\d\w]+\b',  # section 3.1
            r'\bchapter\s+[\d\w]+\b',  # chapter 5
            r'\bfigure\s+[\d\w]+\b',  # figure 2.1
            r'\btable\s+[\d\w]+\b',   # table 3
        ]

        for pattern in file_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities['file_refs'].extend(matches)

        # Date patterns
        date_patterns = [
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # 12/31/2023
            r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',    # 2023-12-31
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
            r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b'
        ]

        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities['dates'].extend(matches)

        # Common document topics (technical/business terms)
        topic_patterns = [
            r'\b(?:project|initiative|research|study|analysis|report|proposal|recommendation|strategy|plan|framework|methodology|approach|implementation|solution|system|process|workflow|procedure|guideline|standard|requirement|specification|documentation|review|assessment|evaluation|audit|investigation)\b'
        ]

        for pattern in topic_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities['topics'].extend(matches)

        # Clean up results
        for entity_type in entities:
            entities[entity_type] = list(set([e.strip() for e in entities[entity_type] if len(e.strip()) > 2]))

        return entities

    def _extract_with_spacy(self, text: str) -> Dict[str, List[str]]:
        """Extract entities using spaCy NER"""
        entities = {
            'people': [],
            'dates': [],
            'topics': [],
            'file_refs': []
        }

        doc = self.nlp(text)

        for ent in doc.ents:
            if ent.label_ == "PERSON":
                entities['people'].append(ent.text.strip())
            elif ent.label_ == "DATE":
                entities['dates'].append(ent.text.strip())
            elif ent.label_ in ["ORG", "PRODUCT", "EVENT"]:
                entities['topics'].append(ent.text.strip())

        return entities

    async def process_pending_chunks(self, batch_size: int = 50) -> int:
        """
        Process chunks with pending entity extraction status
        Returns number of processed chunks
        """
        if not self.db_pool:
            await self.init_db_pool()

        if not self.nlp:
            await self.init_spacy()

        total_processed = 0

        while True:
            # Get pending chunks
            async with self.db_pool.acquire() as conn:
                chunks = await conn.fetch("""
                    SELECT chunk_id, chunk_text
                    FROM document_chunks
                    WHERE entity_extraction_status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT $1
                """, batch_size)

                if not chunks:
                    break

                logger.info(f"Processing {len(chunks)} chunks for entity extraction")

                # Process each chunk
                for chunk in chunks:
                    try:
                        entities = await self.extract_entities(chunk['chunk_text'])

                        # Update database with extracted entities
                        await conn.execute("""
                            UPDATE document_chunks
                            SET entities = $1::jsonb,
                                entity_extraction_status = 'extracted',
                                updated_at = NOW()
                            WHERE chunk_id = $2
                        """, json.dumps(entities), chunk['chunk_id'])

                        total_processed += 1

                    except Exception as e:
                        logger.error(f"Failed to process chunk {chunk['chunk_id']}: {e}")
                        # Mark as failed
                        await conn.execute("""
                            UPDATE document_chunks
                            SET entity_extraction_status = 'failed',
                                updated_at = NOW()
                            WHERE chunk_id = $1
                        """, chunk['chunk_id'])

                logger.info(f"Batch complete: {len(chunks)} chunks processed")

        logger.info(f"Entity extraction complete: {total_processed} total chunks processed")
        return total_processed

    async def get_entity_stats(self) -> Dict:
        """Get entity extraction statistics"""
        if not self.db_pool:
            await self.init_db_pool()

        async with self.db_pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_chunks,
                    COUNT(*) FILTER (WHERE entity_extraction_status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE entity_extraction_status = 'extracted') as extracted,
                    COUNT(*) FILTER (WHERE entity_extraction_status = 'failed') as failed
                FROM document_chunks
            """)

            # Count extracted entities
            entity_counts = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE jsonb_array_length(entities->'people') > 0) as chunks_with_people,
                    COUNT(*) FILTER (WHERE jsonb_array_length(entities->'dates') > 0) as chunks_with_dates,
                    COUNT(*) FILTER (WHERE jsonb_array_length(entities->'topics') > 0) as chunks_with_topics,
                    COUNT(*) FILTER (WHERE jsonb_array_length(entities->'file_refs') > 0) as chunks_with_file_refs
                FROM document_chunks
                WHERE entity_extraction_status = 'extracted'
            """)

            return {
                "processing_stats": dict(stats),
                "entity_stats": dict(entity_counts)
            }

    async def close(self):
        """Clean up resources"""
        if self.db_pool:
            await self.db_pool.close()