"""
Conversation and Message models — Redis-backed.

Redis key schema:
    conv:{conv_id}                → Hash   {user_id, title, model, system_prompt, created_at, updated_at}
    user_convs:{user_id}          → Sorted Set  (score = updated_at timestamp, member = conv_id)
    msgs:{conv_id}                → List   [JSON-encoded message dicts, oldest first]
    msg_counter:{conv_id}         → String (auto-increment counter for message IDs)
    conv_summary:{conv_id}        → String (running conversation summary for context window)

Architecture mirrors the open-webui table-class pattern.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from pydantic import BaseModel


# ──────────────────────────────────────────────
# Pydantic Schemas
# ──────────────────────────────────────────────

class ConversationCreate(BaseModel):
    title: Optional[str] = "New Conversation"
    model: Optional[str] = "gemini-2.5-flash"
    system_prompt: Optional[str] = "You are a helpful assistant."


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    model: str
    system_prompt: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    created_at: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> float:
    return datetime.now(timezone.utc).timestamp()


RECENT_MSG_COUNT = 10


# ──────────────────────────────────────────────
# Table classes — Redis operations
# ──────────────────────────────────────────────

class ConversationsTable:

    @staticmethod
    def _conv_key(conv_id: str) -> str:
        return f"conv:{conv_id}"

    @staticmethod
    def _user_convs_key(user_id: str) -> str:
        return f"user_convs:{user_id}"

    @staticmethod
    def _summary_key(conv_id: str) -> str:
        return f"conv_summary:{conv_id}"

    async def create_conversation(
        self, r: aioredis.Redis, user_id: str, data: ConversationCreate
    ) -> dict:
        conv_id = str(uuid.uuid4())
        now = _now_iso()
        mapping = {
            "id": conv_id,
            "user_id": user_id,
            "title": data.title or "New Conversation",
            "model": data.model or "gemini-2.5-flash",
            "system_prompt": data.system_prompt or "You are a helpful assistant.",
            "created_at": now,
            "updated_at": now,
        }
        pipe = r.pipeline()
        pipe.hset(self._conv_key(conv_id), mapping=mapping)
        pipe.zadd(self._user_convs_key(user_id), {conv_id: _ts()})
        await pipe.execute()
        return mapping

    async def get_conversations_by_user(
        self, r: aioredis.Redis, user_id: str
    ) -> list[dict]:
        conv_ids = await r.zrevrange(self._user_convs_key(user_id), 0, -1)
        if not conv_ids:
            return []

        pipe = r.pipeline()
        for cid in conv_ids:
            pipe.hgetall(self._conv_key(cid))
        results = await pipe.execute()
        return [c for c in results if c]

    async def get_conversation(
        self, r: aioredis.Redis, conversation_id: str, user_id: str
    ) -> Optional[dict]:
        data = await r.hgetall(self._conv_key(conversation_id))
        if not data or data.get("user_id") != user_id:
            return None
        return data

    async def update_conversation(
        self,
        r: aioredis.Redis,
        conversation_id: str,
        user_id: str,
        data: ConversationUpdate,
    ) -> Optional[dict]:
        conv = await self.get_conversation(r, conversation_id, user_id)
        if not conv:
            return None

        update_fields = {k: v for k, v in data.model_dump().items() if v is not None}
        if not update_fields:
            return conv

        update_fields["updated_at"] = _now_iso()
        pipe = r.pipeline()
        pipe.hset(self._conv_key(conversation_id), mapping=update_fields)
        pipe.zadd(self._user_convs_key(user_id), {conversation_id: _ts()})
        await pipe.execute()

        return await self.get_conversation(r, conversation_id, user_id)

    async def delete_conversation(
        self, r: aioredis.Redis, conversation_id: str, user_id: str
    ) -> bool:
        conv = await self.get_conversation(r, conversation_id, user_id)
        if not conv:
            return False

        pipe = r.pipeline()
        pipe.delete(self._conv_key(conversation_id))
        pipe.delete(f"msgs:{conversation_id}")
        pipe.delete(f"msg_counter:{conversation_id}")
        pipe.delete(self._summary_key(conversation_id))
        pipe.zrem(self._user_convs_key(user_id), conversation_id)
        await pipe.execute()
        return True

    # ── Summary helpers ──

    async def get_summary(self, r: aioredis.Redis, conversation_id: str) -> Optional[str]:
        return await r.get(self._summary_key(conversation_id))

    async def set_summary(self, r: aioredis.Redis, conversation_id: str, summary: str):
        await r.set(self._summary_key(conversation_id), summary)


class MessagesTable:

    @staticmethod
    def _msgs_key(conv_id: str) -> str:
        return f"msgs:{conv_id}"

    @staticmethod
    def _counter_key(conv_id: str) -> str:
        return f"msg_counter:{conv_id}"

    async def add_message(
        self, r: aioredis.Redis, conversation_id: str, role: str, content: str
    ) -> dict:
        msg_id = await r.incr(self._counter_key(conversation_id))
        now = _now_iso()
        msg = {
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": now,
        }
        await r.rpush(self._msgs_key(conversation_id), json.dumps(msg))
        return msg

    async def get_messages(
        self, r: aioredis.Redis, conversation_id: str
    ) -> list[dict]:
        raw = await r.lrange(self._msgs_key(conversation_id), 0, -1)
        return [json.loads(m) for m in raw]

    async def get_recent_messages(
        self, r: aioredis.Redis, conversation_id: str, count: int = RECENT_MSG_COUNT
    ) -> list[dict]:
        """Get the last `count` messages (most recent window)."""
        raw = await r.lrange(self._msgs_key(conversation_id), -count, -1)
        return [json.loads(m) for m in raw]

    async def get_message_count(self, r: aioredis.Redis, conversation_id: str) -> int:
        return await r.llen(self._msgs_key(conversation_id))

    async def get_older_messages(
        self, r: aioredis.Redis, conversation_id: str, count: int = RECENT_MSG_COUNT
    ) -> list[dict]:
        """Get all messages EXCEPT the last `count` (the ones to be summarized)."""
        total = await self.get_message_count(r, conversation_id)
        if total <= count:
            return []
        end_idx = total - count - 1
        raw = await r.lrange(self._msgs_key(conversation_id), 0, end_idx)
        return [json.loads(m) for m in raw]

    async def clear_messages(self, r: aioredis.Redis, conversation_id: str) -> bool:
        pipe = r.pipeline()
        pipe.delete(self._msgs_key(conversation_id))
        pipe.delete(self._counter_key(conversation_id))
        await pipe.execute()
        return True


Conversations = ConversationsTable()
Messages = MessagesTable()
