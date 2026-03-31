"""
Vertex AI RAG Engine + Gemini integration with conversation memory.

Context window strategy:
  1. Running summary of older conversation (stored in Redis)
  2. Last N messages verbatim (recent context window)
  3. RAG-retrieved chunks from the Vertex AI corpus for the current query

Authentication:
  - GOOGLE_API_KEY → google.genai SDK for Gemini generation
  - GOOGLE_APPLICATION_CREDENTIALS (service account JSON) → OAuth2 token
    for the Vertex AI retrieveContexts REST API (RAG Engine)

RAG retrieval uses the REST API directly (no heavy SDK dependency):
  POST {location}-aiplatform.googleapis.com/v1beta1/.../:retrieveContexts
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

import httpx
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2 import service_account

from app.core.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

_client = None
_initialized = False

_sa_credentials = None
_sa_token_cache: dict = {"token": None, "expiry": 0}

VERTEX_AI_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def _init_ai():
    global _client, _sa_credentials, _initialized
    if _initialized:
        return

    try:
        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is required")

        from google import genai
        _client = genai.Client(api_key=api_key)
        log.info("Gemini client initialized (google.genai SDK)")

        creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
        if creds_path and settings.RAG_CORPUS_NAME:
            try:
                _sa_credentials = service_account.Credentials.from_service_account_file(
                    creds_path, scopes=VERTEX_AI_SCOPES
                )
                log.info(f"Service account loaded for RAG retrieval: {creds_path}")
            except Exception as e:
                log.warning(f"Could not load service account for RAG: {e}")
                _sa_credentials = None
        elif settings.RAG_CORPUS_NAME:
            log.warning(
                "RAG_CORPUS_NAME is set but GOOGLE_APPLICATION_CREDENTIALS is empty. "
                "RAG retrieval will be disabled. Provide a service account JSON key."
            )

        _initialized = True

    except Exception as e:
        log.error(f"Failed to initialize AI engine: {e}")
        _initialized = False


def _get_access_token() -> str | None:
    """Get a valid OAuth2 access token from the service account, with caching."""
    global _sa_credentials
    if not _sa_credentials:
        return None

    now = time.time()
    if _sa_token_cache["token"] and _sa_token_cache["expiry"] > now + 60:
        return _sa_token_cache["token"]

    _sa_credentials.refresh(AuthRequest())
    _sa_token_cache["token"] = _sa_credentials.token
    _sa_token_cache["expiry"] = _sa_credentials.expiry.timestamp() if _sa_credentials.expiry else now + 3500
    return _sa_credentials.token


# ──────────────────────────────────────────────
# RAG retrieval via REST API
# ──────────────────────────────────────────────

async def retrieve_rag_context(query: str) -> str | None:
    """
    Retrieve relevant chunks from the Vertex AI RAG corpus using the
    retrieveContexts REST endpoint. Requires a service account key.
    See: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/rag-api
    """
    _init_ai()
    if not _sa_credentials or not settings.RAG_CORPUS_NAME:
        return None

    try:
        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(None, _get_access_token)
        if not token:
            log.warning("No access token available for RAG retrieval")
            return None

        location = settings.GCP_LOCATION
        project = settings.GCP_PROJECT_ID
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/{location}:retrieveContexts"
        )

        payload = {
            "vertex_rag_store": {
                "rag_resources": {
                    "rag_corpus": settings.RAG_CORPUS_NAME,
                },
            },
            "query": {
                "text": query,
                "similarity_top_k": 10,
                "rag_retrieval_config": {
                    "filter": {
                        "vector_distance_threshold": 0.5,
                    },
                },
            },
        }

        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

        if resp.status_code != 200:
            log.warning(f"RAG retrieval HTTP {resp.status_code}: {resp.text[:300]}")
            return None

        data = resp.json()
        chunks = []
        contexts = data.get("contexts", {}).get("contexts", [])
        for ctx in contexts:
            text = ctx.get("text", "")
            source = ctx.get("sourceUri", "")
            if text:
                entry = text.strip()
                if source:
                    entry += f"\n[Source: {source}]"
                chunks.append(entry)

        if chunks:
            log.info(f"RAG retrieved {len(chunks)} chunks for query")
            return "\n\n---\n\n".join(chunks)

        return None

    except Exception as e:
        log.warning(f"RAG retrieval failed: {e}")
        return None


# ──────────────────────────────────────────────
# Summarization
# ──────────────────────────────────────────────

async def summarize_messages(
    messages: list[dict],
    existing_summary: str | None = None,
) -> str:
    _init_ai()
    if not _client or not messages:
        return existing_summary or ""

    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )

    prompt = (
        "You are a conversation summarizer. Produce a concise summary "
        "(max 300 words) that captures all key topics, decisions, facts, "
        "and user preferences from the conversation below. "
        "This summary will be used as memory context for future messages, "
        "so preserve any information the user might refer back to.\n\n"
    )

    if existing_summary:
        prompt += f"Previous summary:\n{existing_summary}\n\n"

    prompt += f"New messages to incorporate:\n{transcript}\n\nUpdated summary:"

    try:
        loop = asyncio.get_event_loop()

        def _sync_summarize():
            resp = _client.models.generate_content(
                model=settings.GEMINI_MODEL_NAME,
                contents=prompt,
                config={"temperature": 0.2, "max_output_tokens": 512},
            )
            return resp.text.strip()

        return await loop.run_in_executor(None, _sync_summarize)
    except Exception as e:
        log.warning(f"Summarization failed: {e}")
        return existing_summary or ""


# ──────────────────────────────────────────────
# Context window builder
# ──────────────────────────────────────────────

def build_context_messages(
    system_prompt: str,
    summary: str | None,
    rag_context: str | None,
    recent_messages: list[dict],
) -> list[dict]:
    """
    Assemble the final message list sent to the model:
      [system context + summary + RAG chunks] → [last N messages]
    """
    context_parts = [system_prompt]

    if summary:
        context_parts.append(
            f"\n--- Conversation History Summary ---\n{summary}\n--- End Summary ---"
        )

    if rag_context:
        context_parts.append(
            "\n--- Retrieved Knowledge Base Context ---\n"
            "Use the following information from the knowledge base to answer the user's "
            "question. Cite or reference the context when relevant.\n\n"
            f"{rag_context}\n--- End Context ---"
        )

    context_block = "\n".join(context_parts)

    messages = [
        {"role": "user", "content": context_block},
        {"role": "model", "content": "Understood. I have the conversation history and knowledge base context. I'll use them to help you."},
    ]

    for msg in recent_messages:
        role = "user" if msg["role"] == "user" else "model"
        messages.append({"role": role, "content": msg["content"]})

    return messages


# ──────────────────────────────────────────────
# Streaming generation
# ──────────────────────────────────────────────

async def generate_streaming_response(
    context_messages: list[dict],
) -> AsyncGenerator[str, None]:
    try:
        _init_ai()

        if _client is None:
            yield f"data: {json.dumps({'error': 'AI not configured. Check GOOGLE_API_KEY.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        contents = []
        for msg in context_messages:
            role = msg["role"]
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        loop = asyncio.get_event_loop()

        def _sync_stream():
            return _client.models.generate_content_stream(
                model=settings.GEMINI_MODEL_NAME,
                contents=contents,
                config={
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "max_output_tokens": 8192,
                },
            )

        stream = await loop.run_in_executor(None, _sync_stream)

        full_response = ""
        for chunk in stream:
            text = chunk.text or ""
            if text:
                full_response += text
                data = json.dumps({"content": text, "done": False})
                yield f"data: {data}\n\n"
                await asyncio.sleep(0)

        yield f"data: {json.dumps({'content': '', 'done': True, 'full_response': full_response})}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        log.error(f"Streaming generation error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"


# ──────────────────────────────────────────────
# Title generation
# ──────────────────────────────────────────────

async def generate_title_for_conversation(first_message: str) -> str:
    try:
        _init_ai()
        if _client is None:
            return first_message[:50]

        loop = asyncio.get_event_loop()

        def _sync_title():
            resp = _client.models.generate_content(
                model=settings.GEMINI_MODEL_NAME,
                contents=(
                    f"Generate a concise 3-6 word title for a conversation that starts with: '{first_message}'. "
                    "Return ONLY the title, no quotes, no punctuation at the end."
                ),
                config={"temperature": 0.3, "max_output_tokens": 30},
            )
            return resp.text.strip()

        title = await loop.run_in_executor(None, _sync_title)
        return title or first_message[:50]

    except Exception as e:
        log.warning(f"Title generation failed: {e}")
        return first_message[:50] if len(first_message) > 50 else first_message
