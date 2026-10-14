import { useEffect, useId, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";
import { BusyChatGlow } from "../BusyChatGlow";
import { isThreadTitlePending } from "../chat-sidebar/sections";
import type { FloatingChatWindow } from "./floatingState";
import { FloatingThreadPicker } from "./FloatingThreadPicker";

type Props = {
  activeThread: ChatThread | null;
  isActiveThreadBusy: boolean;
  isActiveThreadUnread: boolean;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onThreadsDeleted: (threadIds: string[], projectId?: string) => void;
  onSelectThread: (windowId: string, threadId: string, thread?: ChatThread) => void;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
};

export function FloatingThreadMenu(props: Props) {
  const { activeThread, isActiveThreadBusy, isActiveThreadUnread, threads, windowItem } = props;
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const id = useId();

  function close(restoreFocus = true) {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      const target = event.target;
      const insidePortal = target instanceof Element && target.closest("[data-chat-picker-scope]")?.getAttribute("data-chat-picker-scope") === id;
      if (target instanceof Node && !menuRef.current?.contains(target) && !insidePortal
        && !menuRef.current?.querySelector('[aria-busy="true"]')) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [id, open]);

  function select(thread: ChatThread) {
    props.onSelectThread(windowItem.id, thread.thread_id, thread);
    close(false);
  }

  return <div className="chat-floating-thread-menu" ref={menuRef} onKeyDown={(event) => {
    if (open && event.key === "Escape" && !event.defaultPrevented && !menuRef.current?.querySelector('[aria-busy="true"]')) {
      event.preventDefault(); event.stopPropagation(); close();
    }
  }}>
    <button ref={triggerRef} type="button" aria-expanded={open} aria-haspopup="dialog" aria-label="Choose chat"
      aria-controls={open ? `${id}-picker` : undefined} aria-describedby={`${id}-state`}
      title={activeThread?.title || "New chat"}
      className={`chat-floating-thread-menu__trigger ${isActiveThreadBusy ? "is-busy" : ""} ${isActiveThreadUnread ? "is-unread" : ""}`}
      onClick={() => { if (!menuRef.current?.querySelector('[aria-busy="true"]')) setOpen((value) => !value); }}>
      {isActiveThreadBusy ? <BusyChatGlow /> : null}
      {isThreadTitlePending(activeThread)
        ? <span aria-label="Generating chat title" className="chat-floating-thread-menu__title-skeleton" role="status" />
        : <span className="chat-floating-thread-menu__trigger-title">{activeThread?.title || "New chat"}</span>}
      <span aria-hidden="true" className="material-symbols-rounded chat-floating-thread-menu__chevron">expand_more</span>
    </button>
    <span id={`${id}-state`} className="chat-floating-thread-menu__accessible-state" role="status">
      {isActiveThreadBusy ? "Chat is working" : isActiveThreadUnread ? "Unread response ready" : ""}
    </span>
    {open ? <div id={`${id}-picker`} className="chat-floating-thread-menu__panel" role="dialog" aria-label="Choose chat">
      <FloatingThreadPicker
        activeThreadId={windowItem.threadId}
        onClose={close}
        onCreateChat={(projectId) => { props.onCreateDraftChat(windowItem.id, projectId); close(false); }}
        onThreadsDeleted={props.onThreadsDeleted}
        onSelectThread={select}
        popupScope={id}
        threads={threads}
      />
    </div> : null}
  </div>;
}
