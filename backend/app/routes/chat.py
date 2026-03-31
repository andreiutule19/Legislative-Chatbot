"""
Chat routes with SSE streaming and conversation memory.

Context window per request:
  1. Running summary of older messages (stored in Redis)
  2. Last 10 messages verbatim
  3. RAG-retrieved chunks from Vertex AI corpus

After each assistant response the summary is updated incrementally
so long conversations don't blow up the token budget.
"""

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.database import get_redis
from app.models.chat import (
    RECENT_MSG_COUNT,
    ChatRequest,
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    Conversations,
    MessageResponse,
    Messages,
)
from app.services.rag_service import (
    build_context_messages,
    generate_streaming_response,
    generate_title_for_conversation,
    retrieve_rag_context,
    summarize_messages,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

DEFAULT_USER = "default"


# ── Conversations ────────────────────────────

@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations():
    r = get_redis()
    convs = await Conversations.get_conversations_by_user(r, DEFAULT_USER)
    return [ConversationResponse(**c) for c in convs]


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(data: ConversationCreate):
    r = get_redis()
    conv = await Conversations.create_conversation(r, DEFAULT_USER, data)
    return ConversationResponse(**conv)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str):
    r = get_redis()
    conv = await Conversations.get_conversation(r, conversation_id, DEFAULT_USER)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(**conv)


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(conversation_id: str, data: ConversationUpdate):
    r = get_redis()
    conv = await Conversations.update_conversation(r, conversation_id, DEFAULT_USER, data)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(**conv)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    r = get_redis()
    deleted = await Conversations.delete_conversation(r, conversation_id, DEFAULT_USER)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Conversation deleted"}


# ── Messages ─────────────────────────────────

@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(conversation_id: str):
    r = get_redis()
    conv = await Conversations.get_conversation(r, conversation_id, DEFAULT_USER)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = await Messages.get_messages(r, conversation_id)
    return [MessageResponse(**m) for m in msgs]


# ── Chat (SSE streaming) ────────────────────

@router.post("/send")
async def send_message(data: ChatRequest):
    r = get_redis()

    if data.conversation_id:
        conv = await Conversations.get_conversation(r, data.conversation_id, DEFAULT_USER)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = conv["id"]
    else:
        conv = await Conversations.create_conversation(
            r, DEFAULT_USER, ConversationCreate()
        )
        conversation_id = conv["id"]

    await Messages.add_message(r, conversation_id, "user", data.message)

    existing_summary = await Conversations.get_summary(r, conversation_id)
    recent_msgs = await Messages.get_recent_messages(r, conversation_id, RECENT_MSG_COUNT)
    total_msgs = await Messages.get_message_count(r, conversation_id)

    needs_summary_update = total_msgs > RECENT_MSG_COUNT and (
        existing_summary is None
        or total_msgs % 4 == 0
    )

    if needs_summary_update:
        older_msgs = await Messages.get_older_messages(r, conversation_id, RECENT_MSG_COUNT)
        if older_msgs:
            new_summary = await summarize_messages(older_msgs, existing_summary)
            if new_summary:
                await Conversations.set_summary(r, conversation_id, new_summary)
                existing_summary = new_summary

    rag_context = await retrieve_rag_context(data.message)

    system_prompt = conv.get("system_prompt") or "You are a helpful assistant."
    history = [{"role": m["role"], "content": m["content"]} for m in recent_msgs]

    context_messages = build_context_messages(
        system_prompt=system_prompt,
        summary=existing_summary,
        rag_context=rag_context,
        recent_messages=history,
    )

    async def event_stream():
        full_response = ""
        async for chunk in generate_streaming_response(context_messages):
            yield chunk

            try:
                if chunk.startswith("data: ") and "[DONE]" not in chunk:
                    payload = json.loads(chunk[6:].strip())
                    if "content" in payload and payload.get("done") is False:
                        full_response += payload["content"]
                    elif payload.get("done") is True and payload.get("full_response"):
                        full_response = payload["full_response"]
            except (json.JSONDecodeError, KeyError):
                pass

        if full_response:
            rr = get_redis()
            await Messages.add_message(rr, conversation_id, "assistant", full_response)

            if not data.conversation_id:
                title = await generate_title_for_conversation(data.message)
                await Conversations.update_conversation(
                    rr, conversation_id, DEFAULT_USER,
                    ConversationUpdate(title=title),
                )

        yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
