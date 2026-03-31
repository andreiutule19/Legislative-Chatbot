import React, { useState } from "react";
import {
  FiPlus,
  FiMessageSquare,
  FiTrash2,
  FiEdit2,
  FiCheck,
  FiX,
  FiChevronLeft,
  FiChevronRight,
} from "react-icons/fi";
import "./Sidebar.css";

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  collapsed,
  onToggle,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  function startEdit(e, conv) {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title);
  }

  function confirmEdit(id) {
    if (editTitle.trim()) {
      onRename(id, editTitle.trim());
    }
    setEditingId(null);
  }

  function handleDelete(e, id) {
    e.stopPropagation();
    onDelete(id);
  }

  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-inner">
        <div className="sidebar-top">
          <button className="new-chat-btn" onClick={onNew}>
            <FiPlus size={16} />
            {!collapsed && <span>New Chat</span>}
          </button>
          <button
            className="collapse-btn"
            onClick={onToggle}
            title={collapsed ? "Expand" : "Collapse"}
          >
            {collapsed ? <FiChevronRight size={16} /> : <FiChevronLeft size={16} />}
          </button>
        </div>

        {!collapsed && (
          <div className="sidebar-search">
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        )}

        <nav className="conversation-list" aria-label="Conversations">
          {filtered.map((conv) => {
            const isActive = conv.id === activeId;
            const isEditing = editingId === conv.id;

            return (
              <button
                key={conv.id}
                className={`conv-item ${isActive ? "active" : ""}`}
                onClick={() => onSelect(conv.id)}
                aria-current={isActive ? "true" : undefined}
                title={conv.title}
              >
                <FiMessageSquare size={14} className="conv-icon" />

                {isEditing ? (
                  <div
                    className="conv-edit"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") confirmEdit(conv.id);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      autoFocus
                    />
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={() => confirmEdit(conv.id)}
                      className="icon-btn"
                    >
                      <FiCheck size={14} />
                    </span>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={() => setEditingId(null)}
                      className="icon-btn"
                    >
                      <FiX size={14} />
                    </span>
                  </div>
                ) : (
                  <>
                    {!collapsed && (
                      <span className="conv-title">{conv.title}</span>
                    )}
                    {!collapsed && isActive && (
                      <span className="conv-actions">
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => startEdit(e, conv)}
                          className="icon-btn"
                          title="Rename"
                        >
                          <FiEdit2 size={13} />
                        </span>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => handleDelete(e, conv.id)}
                          className="icon-btn danger"
                          title="Delete"
                        >
                          <FiTrash2 size={13} />
                        </span>
                      </span>
                    )}
                  </>
                )}
              </button>
            );
          })}

          {filtered.length === 0 && !collapsed && (
            <div className="conv-empty">
              {searchQuery ? "No results found" : "No conversations yet"}
            </div>
          )}
        </nav>
      </div>
    </aside>
  );
}
