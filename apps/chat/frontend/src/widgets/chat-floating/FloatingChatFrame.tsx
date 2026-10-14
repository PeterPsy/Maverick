import type { ActiveAppContext } from "../../lib/activeAppContext";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { ChatVisibilityContext, useChatVisibility } from '../../hooks/useChatVisibility';
import type { ChatThread } from "../../api/client";
import type { ExternalFileDrop, ExternalMentionDrop } from "../../lib/externalInputs";
import { filesFromDataTransfer, hasFileDropData } from "../../lib/fileDropAttachments";
import { appReferenceMentionItemsFromDataTransfer, hasAppReferenceDragData } from "../../lib/storageDragReferences";
import { isThreadBusy, isThreadUnread } from "../chat-sidebar/sections";
import { FloatingLauncher } from "./FloatingLauncher";
import { AppContextButton } from "./AppContextButton";
import { FloatingThreadMenu } from "./FloatingThreadMenu";
import type { FloatingChatWindow } from "./floatingState";

const App = lazy(() => import('../../App').then(module => ({ default: module.App })));

export function FloatingChatFrame({
  activeAppContext = null,
  className = "",
  isActive = true,
  onClose,
  onCollapseChange,
  onCreateDraftChat,
  onDock,
  onMarkThreadRead,
  onOverlay,
  onSelectThread,
  onThreadsDeleted,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  showCollapse = true,
  showClose = true,
  showDock = false,
  showLauncher = false,
  showOverlay = false,
  threads,
  windowItem,
}: {
  activeAppContext?: ActiveAppContext | null;
  className?: string;
  isActive?: boolean;
  onClose: (windowId: string) => void;
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onDock?: (windowId: string) => void;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onOverlay?: (windowId: string) => void;
  onSelectThread: (windowId: string, threadId: string, thread?: ChatThread) => void;
  onThreadsDeleted: (threadIds: string[], projectId?: string) => void;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  showCollapse?: boolean;
  showClose?: boolean;
  showDock?: boolean;
  showLauncher?: boolean;
  showOverlay?: boolean;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
}) {
  const frameRef = useRef<HTMLElement>(null);
  const hostVisible = useChatVisibility();
  useEffect(() => {
    if (hostVisible && isActive && className.includes("mobile-fullscreen")) {
      frameRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    }
  }, [hostVisible, isActive, className]);
  const [externalFileDrop, setExternalFileDrop] = useState<ExternalFileDrop | null>(null);
  const [externalMentionDrop, setExternalMentionDrop] = useState<ExternalMentionDrop | null>(null);
  const [hasOpened, setHasOpened] = useState(isActive && !windowItem.isCollapsed);
  useEffect(() => { if (isActive && !windowItem.isCollapsed) setHasOpened(true); }, [isActive, windowItem.isCollapsed]);
  const retainedThread = windowItem.selectedThread?.thread_id === windowItem.threadId ? windowItem.selectedThread : null;
  const activeThread = threads.find((thread) => thread.thread_id === windowItem.threadId) || retainedThread || null;
  const isActiveThreadBusy = Boolean(activeThread && isThreadBusy(activeThread));
  const isActiveThreadUnread = Boolean(activeThread && isThreadUnread(activeThread));
  const [pinnedContext, setPinnedContext] = useState<ActiveAppContext | null>(null);
  const effectiveContext = pinnedContext || activeAppContext;

  function openCollapsedThread() {
    onCollapseChange(windowItem.id, false);
    if (activeThread) {
      void onMarkThreadRead(activeThread);
    }
  }

  function handleFloatingDragOver(event: DragEvent<HTMLElement>) {
    if (!hasAppReferenceDragData(event.dataTransfer) && !hasFileDropData(event.dataTransfer)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleFloatingDrop(event: DragEvent<HTMLElement>) {
    if (!hasAppReferenceDragData(event.dataTransfer)) {
      const files = filesFromDataTransfer(event.dataTransfer);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      onCollapseChange(windowItem.id, false);
      setExternalFileDrop({
        files,
        requestId: crypto.randomUUID(),
      });
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const items = appReferenceMentionItemsFromDataTransfer(event.dataTransfer);
    if (!items.length) {
      return;
    }
    onCollapseChange(windowItem.id, false);
    setExternalMentionDrop({
      items,
      requestId: crypto.randomUUID(),
    });
  }

  return (
    <>
      {showLauncher ? (
        <FloatingLauncher
          isActiveThreadBusy={isActiveThreadBusy}
          isActiveThreadUnread={isActiveThreadUnread}
          onDragOver={handleFloatingDragOver}
          onDrop={handleFloatingDrop}
          onOpen={openCollapsedThread}
          windowItem={windowItem}
          title={activeThread?.title || "New chat"}
        />
      ) : null}
      <section
        ref={frameRef}
        className={`chat-floating-widget-shell ${windowItem.isCollapsed ? "is-hidden" : ""}${className ? ` ${className}` : ""}`}
        aria-label="Chat"
        onDragOver={handleFloatingDragOver}
        onDrop={handleFloatingDrop}
      >
      <header className="chat-floating-widget-shell__bar">
        <div className="chat-floating-widget-shell__thread-tools">
          <FloatingThreadMenu
            activeThread={activeThread}
            isActiveThreadBusy={isActiveThreadBusy}
            isActiveThreadUnread={isActiveThreadUnread}
            onSelectThread={onSelectThread}
            onThreadsDeleted={onThreadsDeleted}
            onCreateDraftChat={onCreateDraftChat}
            threads={threads}
            windowItem={windowItem}
          />
          <AppContextButton context={effectiveContext} isPinned={Boolean(pinnedContext)}
            onToggle={() => setPinnedContext(pinnedContext ? null : activeAppContext)} />
        </div>
        <div className="chat-floating-widget-shell__actions">
          <button
            aria-label="New chat"
            className="chat-floating-widget-shell__button"
            onClick={() => onCreateDraftChat(windowItem.id, activeThread?.project_id || null)}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              add
            </span>
          </button>
          {showDock ? (
            <button
              aria-label="Dock chat to right"
              className="chat-floating-widget-shell__button"
              onClick={() => onDock?.(windowItem.id)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                right_panel_open
              </span>
            </button>
          ) : null}
          {showOverlay ? (
            <button
              aria-label="Return chat to overlay"
              className="chat-floating-widget-shell__button"
              onClick={() => onOverlay?.(windowItem.id)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                dock_to_right
              </span>
            </button>
          ) : null}
          {showCollapse ? (
            <button
              aria-label="Collapse chat"
              className="chat-floating-widget-shell__button"
              onClick={() => onCollapseChange(windowItem.id, true)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                keyboard_arrow_down
              </span>
            </button>
          ) : null}
          {showClose ? (
            <button
              aria-label="Close chat"
              className="chat-floating-widget-shell__button chat-floating-widget-shell__button--danger chat-floating-widget-shell__button--close"
              onClick={() => onClose(windowItem.id)}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                close
              </span>
            </button>
          ) : null}
        </div>
      </header>
      <div className="chat-floating-widget-shell__body">
        {hasOpened ? (
          <ChatVisibilityContext.Provider value={isActive && !windowItem.isCollapsed}>
            <Suspense fallback={<div className="chat-floating-loading" role="status">Loading chat…</div>}>
              <App
                activeAppContextOverride={effectiveContext}
                externalFileDrop={externalFileDrop}
                externalMentionDrop={externalMentionDrop}
                navigationScope={windowItem.id}
                newChatProjectId={windowItem.draftProjectId}
                newChatRequestId={windowItem.isDraft && !windowItem.threadId ? windowItem.draftRequestId || windowItem.id : null}
                runtimeThreads={threads}
                runtimeThreadsError={runtimeThreadsError}
                runtimeThreadsLoaded={runtimeThreadsLoaded}
                threadId={windowItem.threadId}
              />
            </Suspense>
          </ChatVisibilityContext.Provider>
        ) : null}
      </div>
      </section>
    </>
  );
}
