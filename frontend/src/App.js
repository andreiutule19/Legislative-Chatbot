import React, { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatArea from "./components/ChatArea";
import {
  getConversations,
  getMessages,
  deleteConversation,
  updateConversation,
  sendMessageStream,
} from "./services/api";
import "./App.css";

export default function App() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const abortRef = useRef(false);
  const streamBufferRef = useRef("");

  const loadConversations = useCallback(async () => {
    try {
      const convs = await getConversations();
      setConversations(convs);
    } catch {
      // silently fail
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    getMessages(activeId)
      .then(setMessages)
      .catch(() => setMessages([]));
  }, [activeId]);

  function handleNewChat() {
    setActiveId(null);
    setMessages([]);
    setStreamingContent("");
  }

  async function handleDeleteConversation(id) {
    await deleteConversation(id);
    if (activeId === id) handleNewChat();
    loadConversations();
  }

  async function handleRenameConversation(id, newTitle) {
    await updateConversation(id, { title: newTitle });
    loadConversations();
  }

  async function handleSendMessage(text) {
    abortRef.current = false;
    streamBufferRef.current = "";
    setIsStreaming(true);
    setStreamingContent("");

    const userMsg = { role: "user", content: text, id: Date.now() };
    setMessages((prev) => [...prev, userMsg]);

    sendMessageStream(
      text,
      activeId,
      (chunk) => {
        if (abortRef.current) return;
        streamBufferRef.current += chunk;
        setStreamingContent(streamBufferRef.current);
      },
      (conversationId) => {
        setIsStreaming(false);
        const finalText = streamBufferRef.current;
        setStreamingContent("");
        streamBufferRef.current = "";

        if (finalText) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: finalText, id: Date.now() + 1 },
          ]);
        }

        if (!activeId && conversationId) {
          setActiveId(conversationId);
        }
        loadConversations();
      },
      (error) => {
        setIsStreaming(false);
        const partial = streamBufferRef.current;
        setStreamingContent("");
        streamBufferRef.current = "";
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: partial
              ? partial + `\n\n**Error:** ${error}`
              : `Error: ${error}`,
            id: Date.now() + 1,
          },
        ]);
        loadConversations();
      }
    );
  }

  function handleStopStreaming() {
    abortRef.current = true;
    setIsStreaming(false);
    const finalText = streamBufferRef.current;
    setStreamingContent("");
    streamBufferRef.current = "";

    if (finalText) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: finalText + "\n\n*(Generation stopped)*", id: Date.now() },
      ]);
    }
  }

  return (
    <div className="app-layout">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNewChat}
        onDelete={handleDeleteConversation}
        onRename={handleRenameConversation}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />
      <ChatArea
        messages={messages}
        streamingContent={streamingContent}
        isStreaming={isStreaming}
        onSend={handleSendMessage}
        onStopStreaming={handleStopStreaming}
        activeConversation={conversations.find((c) => c.id === activeId)}
      />
    </div>
  );
}
