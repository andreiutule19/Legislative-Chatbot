import React, { useEffect, useRef, useState } from "react";
import { FiSend, FiSquare } from "react-icons/fi";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import "./ChatArea.css";

function CodeBlock({ className, children, ...props }) {
  const match = /language-(\w+)/.exec(className || "");
  const code = String(children).replace(/\n$/, "");

  if (match) {
    return (
      <SyntaxHighlighter
        style={oneDark}
        language={match[1]}
        PreTag="div"
        customStyle={{ borderRadius: 8, fontSize: "0.85rem", margin: "0.75rem 0" }}
      >
        {code}
      </SyntaxHighlighter>
    );
  }

  return (
    <code className="inline-code" {...props}>
      {children}
    </code>
  );
}

function MessageBubble({ message }) {
  const isUser = message.role === "user";

  return (
    <div className={`message ${isUser ? "message-user" : "message-assistant"}`}>
      <div className="message-inner">
        <div className="message-avatar">
          {isUser ? (
            <span className="avatar-user">U</span>
          ) : (
            <span className="avatar-ai">AI</span>
          )}
        </div>
        <div className="message-content">
          <div className="message-role">{isUser ? "You" : "Assistant"}</div>
          <div className="message-text">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code: CodeBlock,
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="message message-assistant">
      <div className="message-inner">
        <div className="message-avatar">
          <span className="avatar-ai">AI</span>
        </div>
        <div className="message-content">
          <div className="message-role">Assistant</div>
          <div className="typing-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ChatArea({
  messages,
  streamingContent,
  isStreaming,
  onSend,
  onStopStreaming,
  activeConversation,
}) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + "px";
    }
  }, [input]);

  function handleSubmit(e) {
    e?.preventDefault();
    const msg = input.trim();
    if (!msg || isStreaming) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    onSend(msg);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  const allMessages = [
    ...messages,
    ...(streamingContent
      ? [{ role: "assistant", content: streamingContent, id: "streaming" }]
      : []),
  ];

  return (
    <main className="chat-area">
      <div className="messages-container">
        {allMessages.length === 0 && !isStreaming ? (
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h2>RAG Chatbot</h2>
            <p>Powered by Vertex AI RAG Engine</p>
            <div className="empty-hints">
              <div className="hint" onClick={() => setInput("Explain how RAG works in simple terms")}>
                "Explain how RAG works in simple terms"
              </div>
              <div className="hint" onClick={() => setInput("What can you help me with?")}>
                "What can you help me with?"
              </div>
              <div className="hint" onClick={() => setInput("Summarize the latest documents in the knowledge base")}>
                "Summarize the latest documents"
              </div>
            </div>
          </div>
        ) : (
          <div className="messages-list">
            {allMessages.map((msg, i) => (
              <MessageBubble key={msg.id || i} message={msg} />
            ))}
            {isStreaming && !streamingContent && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <div className="input-area">
        <form className="input-form" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message..."
            rows={1}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button type="button" className="stop-btn" onClick={onStopStreaming} title="Stop generating">
              <FiSquare size={16} />
            </button>
          ) : (
            <button type="submit" className="send-btn" disabled={!input.trim()} title="Send message">
              <FiSend size={16} />
            </button>
          )}
        </form>
        <p className="input-disclaimer">
          AI responses are generated using RAG with Vertex AI. Always verify important information.
        </p>
      </div>
    </main>
  );
}
