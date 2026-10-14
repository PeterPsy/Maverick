import { useEffect, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";
import { isMobileComposerInput } from "../../lib/composerDom";
import { ChatConversationPanel } from "../chat-sidebar/ChatConversationPanel";
import { useChatSidebarState } from "../chat-sidebar/useChatSidebarState";
import { ChatSelectionActions } from "../chat-sidebar-footer/ChatSelectionActions";

export function FloatingThreadPicker({ activeThreadId, onClose, onCreateChat, onSelectThread, onThreadsDeleted, popupScope, threads }: {
  activeThreadId: string;
  onClose: () => void;
  onCreateChat: (projectId: string | null) => void;
  onSelectThread: (thread: ChatThread) => void;
  onThreadsDeleted: (threadIds: string[], projectId?: string) => void;
  popupScope: string;
  threads: ChatThread[];
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [isTouch, setIsTouch] = useState(isMobileComposerInput);
  const [isConfirming, setIsConfirming] = useState(false);
  const sidebar = useChatSidebarState({
    activeThreadId, initialThreads: threads, isMobileLayout: isTouch,
    onCreateChat, onSelectThread, onThreadsDeleted,
  });
  useEffect(() => {
    rootRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const media = window.matchMedia?.("(pointer: coarse)");
    const sync = () => setIsTouch(Boolean(media?.matches));
    media?.addEventListener?.("change", sync);
    return () => media?.removeEventListener?.("change", sync);
  }, []);
  useEffect(() => {
    if (!sidebar.hasThreadSelection) setIsConfirming(false);
  }, [sidebar.hasThreadSelection]);

  return <div ref={rootRef} aria-busy={sidebar.isPending} data-no-sidebar-swipe
    className={"bs-widget-root chat-floating-thread-picker " + (isTouch ? "is-shell-mobile " : "") +
      (sidebar.hasThreadSelection ? "has-thread-selection " : "") +
      (sidebar.areThreadActionsRevealed ? "has-thread-actions-revealed" : "")}
    onKeyDown={(event) => {
      if (event.defaultPrevented || (event.target instanceof Element && event.target.closest('[role="menu"]'))) return;
      if (sidebar.isPending || sidebar.expandedThreadId || sidebar.editingProject) return;
      if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation();
        if (isConfirming) setIsConfirming(false);
        else onClose();
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".bs-chat-list__select-button"))
          .filter((button) => !button.closest("[inert]"));
        if (!buttons.length) return;
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = index < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1)
          : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next]?.focus();
      }
    }}>
    <ChatConversationPanel sidebar={sidebar} popupScope={popupScope} />
    {sidebar.hasThreadSelection ? <div className="chat-floating-selection-actions">
      <ChatSelectionActions count={sidebar.selectedThreadIds.size} isDeleting={sidebar.isBulkDeletePending}
        isConfirming={isConfirming} onRequest={() => setIsConfirming(true)}
        onConfirm={() => void sidebar.confirmSelectedThreadDeletion()} onCancel={() => setIsConfirming(false)} />
    </div> : null}
  </div>;
}
