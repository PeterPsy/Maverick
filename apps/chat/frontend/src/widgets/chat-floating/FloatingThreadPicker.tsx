import { useEffect, useState } from "react";
import type { ChatThread } from "../../api/client";
import { SidebarSearch } from "../../components/ui/sidebar-search";
import { isMobileComposerInput } from "../../lib/composerDom";
import { ThreadRow } from "../chat-sidebar/ThreadRow";
import { useSidebarProjects } from "../chat-sidebar/useSidebarProjects";
import { useThreadTouchSelection } from "../chat-sidebar/useThreadTouchSelection";

const NO_MULTI_AGENT_THREADS: ReadonlySet<string> = new Set();

export function FloatingThreadPicker({ activeThreadId, onClose, onRemoveThread, onRenameThread, onSelectThread, canOpenAnotherWindow, threads }: {
  activeThreadId: string;
  onClose: () => void;
  onRemoveThread: (thread: ChatThread) => Promise<void>;
  onRenameThread: (threadId: string, title: string, projectId: string | null) => Promise<void>;
  onSelectThread: (thread: ChatThread, another?: boolean) => void;
  canOpenAnotherWindow: boolean;
  threads: ChatThread[];
}) {
  const [query, setQuery] = useState("");
  const [searchExpanded, setSearchExpanded] = useState(true);
  const [expandedThreadId, setExpandedThreadId] = useState<string | null>(null);
  const [expandedThreadTitle, setExpandedThreadTitle] = useState("");
  const [isTouch, setIsTouch] = useState(isMobileComposerInput);
  const { projects, error, isLoading, refresh } = useSidebarProjects();
  const touch = useThreadTouchSelection({ isShellMobileLayout: isTouch, selectThread: onSelectThread });
  useEffect(() => {
    const media = window.matchMedia?.("(pointer: coarse)");
    const sync = () => setIsTouch(Boolean(media?.matches));
    media?.addEventListener?.("change", sync);
    return () => media?.removeEventListener?.("change", sync);
  }, []);

  const matches = threads.filter((thread) => (thread.title || "New chat").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <div className={`bs-widget-root chat-floating-thread-picker ${isTouch ? "is-shell-mobile" : ""} ${touch.areThreadActionsRevealed ? "has-thread-actions-revealed" : ""}`}
    onKeyDown={(event) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        if (expandedThreadId) return;
        event.preventDefault(); event.stopPropagation(); onClose();
      } else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && !expandedThreadId) {
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".bs-chat-list__select-button"));
        if (!buttons.length) return;
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = index < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1)
          : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next]?.focus();
      }
    }}>
    <SidebarSearch expanded={searchExpanded} onExpandedChange={setSearchExpanded}
      onSearchChange={setQuery} searchQuery={query} placeholder="Search chats" enableShortcut={false} />
    {error ? <div role="alert"><p>{error}</p><button disabled={isLoading} type="button" onClick={() => void refresh()}>Reload project names</button></div> : null}
    {!matches.length ? <p role="status">No chats found.</p> : null}
    {matches.map((thread) => <ThreadRow
      key={thread.thread_id}
      activeThreadId={activeThreadId}
      expandedThreadId={expandedThreadId}
      expandedThreadTitle={expandedThreadTitle}
      isSelected={false}
      isShellMobileLayout={isTouch}
      multiAgentThreadIds={NO_MULTI_AGENT_THREADS}
      onCloseExpandedThread={() => setExpandedThreadId(null)}
      onMoveThread={async (item, projectId) => { await onRenameThread(item.thread_id, item.title, projectId); }}
      onRemoveThread={async (threadId) => { await onRemoveThread(thread); setExpandedThreadId((current) => current === threadId ? null : current); }}
      onRenameThread={onRenameThread}
      onSelectThreadClick={touch.selectThreadFromClick}
      onSelectThreadPointer={touch.selectThreadFromPointer}
      onTrackThreadTouchCancel={touch.cancelThreadTouch}
      onTrackThreadTouchMove={touch.trackThreadTouchMove}
      onSetExpandedThreadTitle={setExpandedThreadTitle}
      onToggleThreadEdit={(item) => { setExpandedThreadId(item.thread_id); setExpandedThreadTitle(item.title || "New chat"); }}
      onTrackThreadTouchStart={touch.trackThreadTouchStart}
      onOpenAnotherThread={canOpenAnotherWindow ? (item) => onSelectThread(item, true) : undefined}
      canMoveThread={false}
      projects={projects}
      sectionProjectId={thread.project_id || null}
      sectionTitle="Chats"
      thread={thread}
    />)}
  </div>;
}
