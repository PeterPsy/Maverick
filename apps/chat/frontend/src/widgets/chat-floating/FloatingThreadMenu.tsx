import { useEffect, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";
import { BusyChatGlow } from "../BusyChatGlow";
import { isThreadBusy, isThreadUnread } from "../chat-sidebar/sections";
import type { FloatingChatWindow } from "./floatingState";

export function FloatingThreadMenu({
  activeThread,
  isActiveThreadBusy,
  isActiveThreadUnread,
  onMarkThreadRead,
  onRemoveThread,
  onRenameThread,
  onSelectThread,
  threads,
  windowItem,
}: {
  activeThread: ChatThread | null;
  isActiveThreadBusy: boolean;
  isActiveThreadUnread: boolean;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onRemoveThread: (windowId: string, thread: ChatThread) => Promise<void>;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
}) {
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editingThreadTitle, setEditingThreadTitle] = useState("");
  const [isThreadMenuOpen, setIsThreadMenuOpen] = useState(false);
  const threadMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isThreadMenuOpen) {
      return;
    }
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || threadMenuRef.current?.contains(target)) {
        return;
      }
      setIsThreadMenuOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsThreadMenuOpen(false);
        setEditingThreadId(null);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isThreadMenuOpen]);

  function selectThread(threadId: string) {
    if (editingThreadId) {
      return;
    }
    setIsThreadMenuOpen(false);
    const thread = threads.find((item) => item.thread_id === threadId);
    if (thread) {
      void onMarkThreadRead(thread);
    }
    onSelectThread(windowItem.id, threadId);
  }

  function startRenameThread(thread: ChatThread) {
    setEditingThreadId(thread.thread_id);
    setEditingThreadTitle(thread.title || "New chat");
  }

  async function saveRenameThread() {
    if (!editingThreadId) {
      return;
    }
    const title = editingThreadTitle.trim();
    if (title) {
      await onRenameThread(editingThreadId, title);
    }
    setEditingThreadId(null);
    setEditingThreadTitle("");
  }

  return (
    <div className="chat-floating-thread-menu" ref={threadMenuRef}>
      <button
        aria-expanded={isThreadMenuOpen}
        aria-haspopup="menu"
        aria-label="Choose chat"
        className={`chat-floating-thread-menu__trigger ${isActiveThreadBusy ? "is-busy" : ""} ${isActiveThreadUnread ? "is-unread" : ""}`}
        disabled={threads.length === 0}
        onClick={() => setIsThreadMenuOpen((current) => !current)}
        type="button"
      >
        {isActiveThreadBusy ? <BusyChatGlow /> : null}
        <span className="chat-floating-thread-menu__trigger-title">{activeThread?.title || "New chat"}</span>
        <span aria-hidden="true" className="material-symbols-rounded chat-floating-thread-menu__chevron">
          expand_more
        </span>
      </button>
      {isThreadMenuOpen ? (
        <div className="chat-floating-thread-menu__panel" role="menu">
          {threads.map((thread) => {
            const isBusy = isThreadBusy(thread);
            const isUnread = isThreadUnread(thread);
            const isEditing = editingThreadId === thread.thread_id;
            return (
              <div
                className={`chat-floating-thread-menu__item ${windowItem.threadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""} ${
                  isUnread ? "is-unread" : ""
                }`}
                key={thread.thread_id}
                role="menuitem"
              >
                {isBusy ? <BusyChatGlow /> : null}
                {isEditing ? (
                  <input
                    aria-label="Rename chat"
                    autoFocus
                    className="chat-floating-thread-menu__rename-input"
                    onChange={(event) => setEditingThreadTitle(event.target.value)}
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void saveRenameThread();
                      }
                      if (event.key === "Escape") {
                        setEditingThreadId(null);
                        setEditingThreadTitle("");
                      }
                    }}
                    value={editingThreadTitle}
                  />
                ) : (
                  <button className="chat-floating-thread-menu__item-select" onClick={() => selectThread(thread.thread_id)} type="button">
                    <span className="chat-floating-thread-menu__item-copy">
                      <span className="chat-floating-thread-menu__item-title">{thread.title || "New chat"}</span>
                    </span>
                  </button>
                )}
                <div className="chat-floating-thread-menu__item-actions">
                  <button
                    aria-label={`Rename ${thread.title || "chat"}`}
                    className="chat-floating-thread-menu__icon-action"
                    onClick={(event) => {
                      event.stopPropagation();
                      startRenameThread(thread);
                    }}
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">
                      edit
                    </span>
                  </button>
                  <button
                    aria-label={`Delete ${thread.title || "chat"}`}
                    className="chat-floating-thread-menu__icon-action is-danger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void onRemoveThread(windowItem.id, thread);
                    }}
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">
                      delete
                    </span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
