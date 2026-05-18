"""
Context-Aware Response Generator
Integrates with LLMs to provide intelligent responses when context injection occurs
"""

import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

if not ANTHROPIC_AVAILABLE and not OPENAI_AVAILABLE:
    logging.warning("Neither Anthropic nor OpenAI available, using template responses")

from document_entities import DocumentExtractedEntities
from redis_context_buffer import LiveContextMessage

logger = logging.getLogger(__name__)

@dataclass
class ContextualResponse:
    """Response with context and metadata"""
    response_text: str
    context_sources: List[str]      # Source message IDs
    confidence: str                 # 'high', 'medium', 'low'
    gap_created: bool
    gap_id: Optional[str]
    processing_time_ms: float

class ContextAwareResponder:
    """
    Generates intelligent responses using injected context

    When context overlap detected:
    1. Gather relevant context messages
    2. Structure context for LLM prompt
    3. Generate natural language response
    4. Include source attribution
    """

    def __init__(self, anthropic_api_key: Optional[str] = None, openai_api_key: Optional[str] = None):
        self.anthropic_client = None
        self.openai_client = None

        # Initialize Anthropic client (preferred for hardware engineering)
        if ANTHROPIC_AVAILABLE and anthropic_api_key:
            self.anthropic_client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

        # Initialize OpenAI client as alternative
        elif OPENAI_AVAILABLE and openai_api_key:
            self.openai_client = openai.AsyncOpenAI(api_key=openai_api_key)

        # Template responses for fallback
        self.template_responses = {
            'high_confidence': (
                "Based on related information in your documents about {topics}, "
                "here's what you should know: {context_summary}"
            ),
            'medium_confidence': (
                "I found some related information about {topics}. "
                "You might want to explore {mentioned_documents} for details."
            ),
            'gap_created': (
                "I've flagged this as a potential information gap since "
                "relevant {topics} information exists in your documents. "
                "Here's the context: {context_summary}"
            )
        }

    async def generate_response(
        self,
        user_message: str,
        user_entities: DocumentExtractedEntities,
        matching_contexts: List[Dict],
        user_id: str,
        gap_created: bool = False,
        gap_id: Optional[str] = None
    ) -> ContextualResponse:
        """
        Generate context-aware response for user query

        Args:
            user_message: The user's original message
            user_entities: Entities extracted from user message
            matching_contexts: List of overlapping context messages
            user_id: ID of user who sent message
            gap_created: Whether a gap was created
            gap_id: ID of created gap if any

        Returns:
            ContextualResponse with generated text and metadata
        """
        start_time = time.time()

        try:
            # Structure context for response generation
            context_data = self._structure_context(matching_contexts, user_entities)

            # Generate response with LLM or fallback
            if self.anthropic_client:
                response_text = await self._generate_with_anthropic(
                    user_message, user_entities, context_data, user_id, gap_created
                )
                confidence = 'high'
            elif self.openai_client:
                response_text = await self._generate_with_openai(
                    user_message, user_entities, context_data, user_id, gap_created
                )
                confidence = 'high'
            else:
                response_text = self._generate_with_template(
                    user_entities, context_data, gap_created
                )
                confidence = 'medium'

            # Extract source message IDs
            context_sources = [
                ctx['message'].message_id for ctx in matching_contexts
            ]

            processing_time = (time.time() - start_time) * 1000

            return ContextualResponse(
                response_text=response_text,
                context_sources=context_sources,
                confidence=confidence,
                gap_created=gap_created,
                gap_id=gap_id,
                processing_time_ms=processing_time
            )

        except Exception as e:
            logger.error(f"Failed to generate context response: {e}")
            processing_time = (time.time() - start_time) * 1000

            return ContextualResponse(
                response_text=f"I found some related discussion but had trouble processing it. Error: {str(e)}",
                context_sources=[],
                confidence='low',
                gap_created=gap_created,
                gap_id=gap_id,
                processing_time_ms=processing_time
            )

    def _structure_context(
        self,
        matching_contexts: List[Dict],
        user_entities: DocumentExtractedEntities
    ) -> Dict:
        """Structure context data for response generation"""

        # Extract overlapping entities
        overlapping_topics = set()
        overlapping_reqs = set()
        mentioned_users = set()
        context_messages = []

        for ctx in matching_contexts:
            msg = ctx['message']
            msg_entities = msg.entities

            # Find overlaps
            overlapping_topics.update(
                set(user_entities.components) & set(msg_entities.get('components', []))
            )
            overlapping_reqs.update(
                set(user_entities.reqs) & set(msg_entities.get('reqs', []))
            )
            mentioned_users.update(msg_entities.get('users_mentioned', []))

            # Summarize context message
            context_messages.append({
                'user_id': msg.user_id,
                'text': msg.text[:200] + "..." if len(msg.text) > 200 else msg.text,
                'timestamp': msg.timestamp,
                'confidence': ctx.get('confidence', 'medium'),
                'entities': msg_entities
            })

        # Sort by timestamp (most recent first)
        context_messages.sort(key=lambda x: x['timestamp'], reverse=True)

        return {
            'overlapping_topics': list(overlapping_topics),
            'overlapping_reqs': list(overlapping_reqs),
            'mentioned_users': list(mentioned_users),
            'context_messages': context_messages[:3],  # Top 3 most relevant
            'total_context_count': len(matching_contexts)
        }

    async def _generate_with_anthropic(
        self,
        user_message: str,
        user_entities: DocumentExtractedEntities,
        context_data: Dict,
        user_id: str,
        gap_created: bool
    ) -> str:
        """Generate response using Claude Sonnet with structured context"""

        # Build context summary for prompt
        context_summary = self._build_context_summary(context_data)

        # Craft system prompt for document Q&A context
        system_prompt = """You are an AI assistant for document-based knowledge retrieval. Your role is to provide helpful context when users ask questions about topics covered in their document collection.

Key guidelines:
- Be concise and focus on actionable information
- Reference specific document sections or files when relevant
- Highlight potential information gaps in the document set
- Use appropriate terminology based on document content
- Include relevant document sources when helpful"""

        # Build user prompt with context
        user_prompt = f"""A user (@{user_id}) just asked: "{user_message}"

I found related information in your documents about the same topics:

{context_summary}

{"🚨 NOTE: This appears to be missing from your current document set, so I've created an information gap alert." if gap_created else ""}

Please provide a helpful response that:
1. Summarizes the relevant document content
2. Highlights key information or findings
3. Suggests related documents or sections to explore
4. Keeps it concise (2-3 sentences max)

Response:"""

        try:
            response = await self.anthropic_client.messages.create(
                model="claude-3-sonnet-20240229",  # Use Sonnet for quality
                max_tokens=300,
                temperature=0.3,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )

            return response.content[0].text.strip()

        except Exception as e:
            logger.error(f"Anthropic generation failed: {e}")
            return self._generate_with_template(user_entities, context_data, gap_created)

    async def _generate_with_openai(
        self,
        user_message: str,
        user_entities: DocumentExtractedEntities,
        context_data: Dict,
        user_id: str,
        gap_created: bool
    ) -> str:
        """Generate response using OpenAI GPT with structured context"""

        # Build context summary for prompt
        context_summary = self._build_context_summary(context_data)

        # Craft system prompt for document Q&A context
        system_prompt = """You are an AI assistant for document-based knowledge retrieval. Your role is to provide helpful context when users ask questions about topics covered in their document collection.

Key guidelines:
- Be concise and focus on actionable information
- Reference specific document sections or files when relevant
- Highlight potential information gaps in the document set
- Use appropriate terminology based on document content
- Include relevant document sources when helpful"""

        # Build user prompt with context
        user_prompt = f"""A user (@{user_id}) just asked: "{user_message}"

I found related information in your documents about the same topics:

{context_summary}

{"🚨 NOTE: This appears to be missing from your current document set, so I've created an information gap alert." if gap_created else ""}

Please provide a helpful response that:
1. Summarizes the relevant document content
2. Highlights key information or findings
3. Suggests related documents or sections to explore
4. Keeps it concise (2-3 sentences max)

Response:"""

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4",  # Use GPT-4 for quality
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=300,
                temperature=0.3
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}")
            return self._generate_with_template(user_entities, context_data, gap_created)

    def _generate_with_template(
        self,
        user_entities: DocumentExtractedEntities,
        context_data: Dict,
        gap_created: bool
    ) -> str:
        """Fallback template-based response generation"""

        components = context_data.get('overlapping_topics', [])
        reqs = context_data.get('overlapping_reqs', [])
        users = context_data.get('mentioned_users', [])
        context_messages = context_data.get('context_messages', [])

        # Build context summary
        context_summary = []
        for msg in context_messages[:2]:
            summary = f"{msg['user_id']}: {msg['text'][:100]}..."
            context_summary.append(summary)

        # Choose template based on situation
        if gap_created:
            template = self.template_responses['gap_created']
        elif reqs or len(components) >= 2:
            template = self.template_responses['high_confidence']
        else:
            template = self.template_responses['medium_confidence']

        # Format template
        return template.format(
            topics=', '.join(components) if components else 'the mentioned topics',
            context_summary=' | '.join(context_summary),
            mentioned_documents=', '.join(users) if users else 'related documents',
            reqs=', '.join(reqs) if reqs else ''
        )

    def _build_context_summary(self, context_data: Dict) -> str:
        """Build structured context summary for LLM prompt"""

        lines = []

        # Components and requirements
        if context_data.get('overlapping_topics'):
            lines.append(f"📋 Topics: {', '.join(context_data['overlapping_topics'])}")

        if context_data.get('overlapping_reqs'):
            lines.append(f"📑 Requirements: {', '.join(context_data['overlapping_reqs'])}")

        # Context messages
        lines.append("\n🕐 Recent discussions:")
        for i, msg in enumerate(context_data.get('context_messages', [])[:3], 1):
            timestamp = datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00'))
            time_ago = self._time_ago(timestamp)
            lines.append(f"{i}. @{msg['user_id']} ({time_ago}): {msg['text']}")

        # Mentioned users
        if context_data.get('mentioned_users'):
            lines.append(f"\n👥 People involved: {', '.join(context_data['mentioned_users'])}")

        return '\n'.join(lines)

    def _time_ago(self, timestamp: datetime) -> str:
        """Calculate human-readable time ago"""
        now = datetime.now(timestamp.tzinfo)
        diff = now - timestamp

        if diff.days > 0:
            return f"{diff.days}d ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours}h ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes}m ago"
        else:
            return "just now"

class ResponseCache:
    """Cache responses for repeated queries to improve performance"""

    def __init__(self, max_size: int = 100, ttl_minutes: int = 30):
        self.cache = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_minutes * 60

    def _generate_key(self, user_message: str, context_sources: List[str]) -> str:
        """Generate cache key from message and context"""
        context_key = '_'.join(sorted(context_sources))
        return f"{hash(user_message)}_{hash(context_key)}"

    def get(self, user_message: str, context_sources: List[str]) -> Optional[ContextualResponse]:
        """Get cached response if valid"""
        key = self._generate_key(user_message, context_sources)

        if key in self.cache:
            cached_response, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                logger.debug(f"Cache hit for response key {key[:8]}...")
                return cached_response
            else:
                del self.cache[key]  # Expired

        return None

    def set(self, user_message: str, context_sources: List[str], response: ContextualResponse):
        """Cache response with TTL"""
        if len(self.cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]

        key = self._generate_key(user_message, context_sources)
        self.cache[key] = (response, time.time())
        logger.debug(f"Cached response for key {key[:8]}...")

# Enhanced responder with caching
class CachedContextResponder(ContextAwareResponder):
    """Context responder with response caching for better performance"""

    def __init__(self, anthropic_api_key: Optional[str] = None, openai_api_key: Optional[str] = None):
        super().__init__(anthropic_api_key, openai_api_key)
        self.cache = ResponseCache()

    async def generate_response(
        self,
        user_message: str,
        user_entities: DocumentExtractedEntities,
        matching_contexts: List[Dict],
        user_id: str,
        gap_created: bool = False,
        gap_id: Optional[str] = None
    ) -> ContextualResponse:
        """Generate response with caching"""

        context_sources = [ctx['message'].message_id for ctx in matching_contexts]

        # Check cache first
        cached_response = self.cache.get(user_message, context_sources)
        if cached_response and not gap_created:  # Don't cache gap creation responses
            return cached_response

        # Generate new response
        response = await super().generate_response(
            user_message, user_entities, matching_contexts,
            user_id, gap_created, gap_id
        )

        # Cache if successful and not gap-related
        if not gap_created and response.confidence in ['high', 'medium']:
            self.cache.set(user_message, context_sources, response)

        return response

# Testing and example usage
if __name__ == "__main__":
    import asyncio
    from redis_context_buffer import LiveContextMessage

    async def test_response_generation():
        """Test context-aware response generation"""
        responder = CachedContextResponder()

        # Mock context data
        mock_message = LiveContextMessage(
            message_id="msg_001",
            user_id="alice",
            text="Found comprehensive analysis of renewable energy integration requirements in sustainability report",
            entities={
                'file_refs': ['sustainability_report.pdf'],
                'topics': ['renewable_energy', 'integration'],
                'people': ['@bob'],
                'dates': ['2024-Q1']
            },
            conversation_id="conv_001",
            timestamp="2024-01-15T14:30:00Z",
            document_scope="project-docs"
        )

        mock_contexts = [
            {
                'message': mock_message,
                'confidence': 'high',
                'score': 2.5
            }
        ]

        # User B asks about energy requirements
        user_entities = DocumentExtractedEntities(
            reqs=[],
            components=['renewable_energy', 'integration'],
            users_mentioned=[],
            topics=['energy_requirements'],
            confidence=0.8,
            extraction_time_ms=180
        )

        # Generate response
        response = await responder.generate_response(
            user_message="What are the current renewable energy integration requirements?",
            user_entities=user_entities,
            matching_contexts=mock_contexts,
            user_id="bob",
            gap_created=True,
            gap_id="248"
        )

        print("Generated Response:")
        print(f"Text: {response.response_text}")
        print(f"Confidence: {response.confidence}")
        print(f"Sources: {response.context_sources}")
        print(f"Gap created: {response.gap_created}")
        print(f"Processing time: {response.processing_time_ms:.1f}ms")

    # Run test
    asyncio.run(test_response_generation())