"""
Redis Live Context Buffer for Two-Tier Architecture
Handles real-time message context storage with 2-hour TTL
"""

import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
import redis.asyncio as redis
import logging

logger = logging.getLogger(__name__)

@dataclass
class LiveContextMessage:
    """Schema for document Q&A queries in Redis live buffer"""
    message_id: str
    user_id: str
    text: str
    entities: Dict[str, List[str]]  # people, topics, dates, file_refs
    conversation_id: Optional[str]  # Link to SQL conversation history
    timestamp: str
    document_scope: str             # "all" or specific document_id

    def to_redis_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_redis_json(cls, data: str) -> 'LiveContextMessage':
        return cls(**json.loads(data))

class RedisContextBuffer:
    """
    Two-tier architecture Tier 1: Live conversation buffer

    Stores last 30 queries per document scope with 2-hour TTL
    Optimized for 5-minute real-time context lookup in document Q&A
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None

        # Configuration
        self.BUFFER_TTL = 7200  # 2 hours in seconds
        self.MAX_QUERIES_PER_SCOPE = 30

    async def connect(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.from_url(self.redis_url)
            await self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {self.redis_url}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("🔌 Disconnected from Redis")

    def _get_channel_key(self, channel_id: str) -> str:
        """Get Redis key for channel context buffer"""
        return f"channel:{channel_id}:context"

    async def add_message(
        self,
        channel_id: str,
        message: LiveContextMessage
    ) -> bool:
        """
        Add message to channel's live context buffer

        Uses Redis ZADD with timestamp scoring for chronological ordering
        Maintains max 30 messages per channel with automatic cleanup
        """
        if not self.redis_client:
            logger.error("Redis client not connected")
            return False

        try:
            key = self._get_channel_key(channel_id)
            timestamp_score = time.time()

            # Add message with timestamp as score
            await self.redis_client.zadd(
                key,
                {message.to_redis_json(): timestamp_score}
            )

            # Trim to keep only last N messages
            await self.redis_client.zremrangebyrank(
                key,
                0,
                -(self.MAX_MESSAGES_PER_CHANNEL + 1)
            )

            # Set TTL (refreshes on each new message)
            await self.redis_client.expire(key, self.BUFFER_TTL)

            logger.debug(f"📝 Added message {message.message_id} to {channel_id} buffer")
            return True

        except Exception as e:
            logger.error(f"Failed to add message to Redis buffer: {e}")
            return False

    async def get_recent_context(
        self,
        channel_id: str,
        max_messages: int = 30,
        max_age_minutes: int = 120  # 2 hours default
    ) -> List[LiveContextMessage]:
        """
        Get recent messages from channel buffer for context injection

        Returns messages in reverse chronological order (newest first)
        Filters by max_age_minutes for additional time-based filtering
        """
        if not self.redis_client:
            logger.warning("Redis client not connected, returning empty context")
            return []

        try:
            key = self._get_channel_key(channel_id)

            # Get recent messages (newest first)
            raw_messages = await self.redis_client.zrevrange(
                key, 0, max_messages - 1, withscores=True
            )

            if not raw_messages:
                return []

            # Parse messages and filter by age
            cutoff_timestamp = time.time() - (max_age_minutes * 60)
            context_messages = []

            for raw_msg, timestamp_score in raw_messages:
                if timestamp_score >= cutoff_timestamp:
                    try:
                        message = LiveContextMessage.from_redis_json(raw_msg.decode())
                        context_messages.append(message)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse message from Redis: {e}")
                        continue

            logger.debug(f"📖 Retrieved {len(context_messages)} context messages from {channel_id}")
            return context_messages

        except Exception as e:
            logger.error(f"Failed to get context from Redis: {e}")
            return []

    async def get_channel_stats(self, channel_id: str) -> Dict:
        """Get statistics about channel buffer"""
        if not self.redis_client:
            return {"error": "Redis not connected"}

        try:
            key = self._get_channel_key(channel_id)

            # Get count and TTL
            message_count = await self.redis_client.zcard(key)
            ttl = await self.redis_client.ttl(key)

            # Get oldest and newest timestamps
            oldest = await self.redis_client.zrange(key, 0, 0, withscores=True)
            newest = await self.redis_client.zrange(key, -1, -1, withscores=True)

            oldest_ts = oldest[0][1] if oldest else None
            newest_ts = newest[0][1] if newest else None

            return {
                "channel_id": channel_id,
                "message_count": message_count,
                "ttl_seconds": ttl,
                "oldest_message": datetime.fromtimestamp(oldest_ts).isoformat() if oldest_ts else None,
                "newest_message": datetime.fromtimestamp(newest_ts).isoformat() if newest_ts else None,
                "buffer_age_minutes": (time.time() - oldest_ts) / 60 if oldest_ts else None
            }

        except Exception as e:
            logger.error(f"Failed to get channel stats: {e}")
            return {"error": str(e)}

    async def cleanup_expired_channels(self) -> int:
        """
        Cleanup expired channel buffers (maintenance operation)
        Returns count of cleaned up channels
        """
        if not self.redis_client:
            return 0

        try:
            # Find all channel keys
            channel_keys = await self.redis_client.keys("channel:*:context")

            cleaned_count = 0
            for key in channel_keys:
                ttl = await self.redis_client.ttl(key)
                if ttl == -2:  # Key expired/doesn't exist
                    cleaned_count += 1

            logger.info(f"🧹 Cleaned up {cleaned_count} expired channel buffers")
            return cleaned_count

        except Exception as e:
            logger.error(f"Failed to cleanup expired channels: {e}")
            return 0

    async def extend_ttl_for_active_channels(self, channel_ids: List[str]) -> int:
        """
        Extend TTL for channels with active entity references
        Used to prevent dead zones for important ongoing discussions
        """
        if not self.redis_client:
            return 0

        extended_count = 0
        for channel_id in channel_ids:
            try:
                key = self._get_channel_key(channel_id)
                current_ttl = await self.redis_client.ttl(key)

                if current_ttl > 0 and current_ttl < 3600:  # Less than 1 hour left
                    await self.redis_client.expire(key, self.BUFFER_TTL)
                    extended_count += 1
                    logger.debug(f"🔄 Extended TTL for active channel {channel_id}")

            except Exception as e:
                logger.warning(f"Failed to extend TTL for {channel_id}: {e}")
                continue

        return extended_count

# Context manager for easy usage
class RedisContextManager:
    """Context manager for Redis buffer operations"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.buffer = RedisContextBuffer(redis_url)

    async def __aenter__(self):
        await self.buffer.connect()
        return self.buffer

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.buffer.disconnect()

# Example usage and testing
if __name__ == "__main__":
    import asyncio

    async def test_redis_buffer():
        """Test Redis context buffer functionality"""
        async with RedisContextManager() as buffer:
            # Test message
            test_message = LiveContextMessage(
                message_id="test_123",
                user_id="alice",
                text="Document analysis reveals new sustainability requirements for renewable energy integration",
                entities={
                    "file_refs": ["sustainability_policy.pdf"],
                    "topics": ["renewable_energy", "sustainability"],
                    "people": ["@bob", "@erik"]
                },
                conversation_id="conv_20240115_001",
                timestamp=datetime.now().isoformat(),
                document_scope="project-docs"
            )

            # Add to buffer
            success = await buffer.add_message("project-docs", test_message)
            print(f"Add message success: {success}")

            # Get context
            context = await buffer.get_recent_context("project-docs", max_messages=10)
            print(f"Retrieved {len(context)} context messages")

            # Get stats
            stats = await buffer.get_channel_stats("project-docs")
            print(f"Channel stats: {stats}")

    # Run test
    if __name__ == "__main__":
        asyncio.run(test_redis_buffer())