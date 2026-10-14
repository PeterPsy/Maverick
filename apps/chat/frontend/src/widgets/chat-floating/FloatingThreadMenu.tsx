import { useEffect, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";
import { BusyChatGlow } from "../BusyChatGlow";
import { isThreadBusy, isThreadTitlePending, isThreadUnread } from "../chat-sidebar/sections";
import type { FloatingChatWindow } from "./floatingState";

type Props = {
  activeThread: ChatThread | null;
  isActiveThreadBusy: boolean;
  isActiveThreadUnread: boolean;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onRemoveThread: (windowId: string, thread: ChatThread) => Promise<void>;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
  onOpenAnotherThread?: (windowId: string, threadId: string) => void;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
};

export function FloatingThreadMenu(props: Props) {
  const { activeThread, isActiveThreadBusy, isActiveThreadUnread, threads, windowItem } = props;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    setEditingId(null);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  async function mutate(action: () => Promise<void>, after?: () => void) {
    if (pending) return;
    setPending(true);
    setError(null);
    try { await action(); after?.(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to update chat. Try again."); }
    finally { setPending(false); }
  }

  function select(thread: ChatThread, another = false) {
    if (pending) return;
    if (another) props.onOpenAnotherThread?.(windowItem.id, thread.thread_id);
    else props.onSelectThread(windowItem.id, thread.thread_id);
    void props.onMarkThreadRead(thread);
    close();
  }

  const matches = threads.filter((thread) => (thread.title || "New chat").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <div className="chat-floating-thread-menu" ref={menuRef} onKeyDown={(event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !editingId) {
      const buttons = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>(".chat-floating-thread-menu__item-select") || []);
      if (!buttons.length) return;
      event.preventDefault();
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const nextIndex = index < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1)
        : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[nextIndex]?.focus();
    }
  }}>
    <button ref={triggerRef} type="button" aria-expanded={open} aria-haspopup="dialog" aria-label="Choose chat"
      title={activeThread?.title || "New chat"}
      className={`chat-floating-thread-menu__trigger ${isActiveThreadBusy ? "is-busy" : ""} ${isActiveThreadUnread ? "is-unread" : ""}`}
      onClick={() => { setQuery(""); setError(null); setOpen((value) => !value); }}>
      {isActiveThreadBusy ? <BusyChatGlow /> : null}
      {isThreadTitlePending(activeThread)
        ? <span aria-label="Generating chat title" className="chat-floating-thread-menu__title-skeleton" role="status" />
        : <span className="chat-floating-thread-menu__trigger-title">{activeThread?.title || "New chat"}</span>}
      <span className="chat-floating-thread-menu__state">{isActiveThreadBusy ? "Working" : isActiveThreadUnread ? "Ready" : ""}</span>
      <span aria-hidden="true" className="material-symbols-rounded chat-floating-thread-menu__chevron">expand_more</span>
    </button>
    {open ? <div className="chat-floating-thread-menu__panel" role="dialog" aria-label="Choose chat">
      <input autoFocus aria-label="Search chats" className="chat-floating-thread-menu__search" value={query} onChange={(event) => setQuery(event.target.value)} />
      {error ? <p role="alert">{error}</p> : null}
      {!matches.length ? <p role="status">No chats found.</p> : null}
      {matches.map((thread) => {
        const label = thread.title || "New chat";
        const editing = editingId === thread.thread_id;
        return <div key={thread.thread_id} className={`chat-floating-thread-menu__item ${windowItem.threadId === thread.thread_id ? "is-active" : ""} ${isThreadBusy(thread) ? "is-busy" : ""} ${isThreadUnread(thread) ? "is-unread" : ""}`}>
          {isThreadBusy(thread) ? <BusyChatGlow /> : null}
          {editing ? <input autoFocus aria-label="Rename chat" className="chat-floating-thread-menu__rename-input" value={editingTitle}
            onChange={(event) => setEditingTitle(event.target.value)} onKeyDown={(event) => {
              if (event.key === "Enter" && editingTitle.trim()) {
                event.preventDefault();
                void mutate(() => props.onRenameThread(thread.thread_id, editingTitle.trim()), () => setEditingId(null));
              }
            }} /> : <button type="button" className="chat-floating-thread-menu__item-select" disabled={pending} onClick={() => select(thread)}>
              <span className="chat-floating-thread-menu__item-title" title={label}>{label}</span>
            </button>}
          <div className="chat-floating-thread-menu__item-actions">
            {editing ? <>
              <button type="button" aria-label="Save rename" disabled={pending || !editingTitle.trim()} onClick={() => void mutate(() => props.onRenameThread(thread.thread_id, editingTitle.trim()), () => setEditingId(null))}>Save</button>
              <button type="button" disabled={pending} onClick={() => setEditingId(null)}>Cancel</button>
            </> : <>
              {props.onOpenAnotherThread ? <button type="button" className="chat-floating-thread-menu__icon-action" aria-label={`Open ${label} in another window`} disabled={pending} onClick={() => select(thread, true)}><span aria-hidden="true" className="material-symbols-rounded">open_in_new</span></button> : null}
              <button type="button" className="chat-floating-thread-menu__icon-action" aria-label={`Rename ${label}`} disabled={pending || isThreadTitlePending(thread)} onClick={() => { setEditingId(thread.thread_id); setEditingTitle(label); }}><span aria-hidden="true" className="material-symbols-rounded">edit</span></button>
              <button type="button" className="chat-floating-thread-menu__icon-action is-danger" aria-label={`Delete ${label}`} disabled={pending} onClick={() => void mutate(() => props.onRemoveThread(windowItem.id, thread))}><span aria-hidden="true" className="material-symbols-rounded">delete</span></button>
            </>}
          </div>
        </div>;
      })}
    </div> : null}
  </div>;
}
