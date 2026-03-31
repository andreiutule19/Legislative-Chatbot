const API_BASE = process.env.REACT_APP_API_URL ?? "";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

// ── Conversations ──

export async function getConversations() {
  return request("/api/chat/conversations");
}

export async function updateConversation(id, data) {
  return request(`/api/chat/conversations/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteConversation(id) {
  return request(`/api/chat/conversations/${id}`, { method: "DELETE" });
}

// ── Messages ──

export async function getMessages(conversationId) {
  return request(`/api/chat/conversations/${conversationId}/messages`);
}

// ── Chat (SSE streaming) ──

export async function sendMessageStream(message, conversationId, onChunk, onDone, onError) {
  try {
    const res = await fetch(`${API_BASE}/api/chat/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      onError(body.detail || `Request failed: ${res.status}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let receivedConversationId = null;
    let errorMessage = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (payload === "[DONE]") continue;

        try {
          const data = JSON.parse(payload);

          if (data.error) {
            errorMessage = data.error;
          } else if (data.conversation_id) {
            receivedConversationId = data.conversation_id;
          } else if (data.content !== undefined && !data.done) {
            onChunk(data.content);
          }
        } catch {
          // skip malformed JSON
        }
      }
    }

    if (errorMessage) {
      onError(errorMessage);
    }
    if (receivedConversationId) {
      onDone(receivedConversationId);
    }
  } catch (err) {
    onError(err.message);
  }
}
