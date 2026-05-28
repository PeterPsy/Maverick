import { useState } from "react";
import type { DragEvent } from "react";
import { App } from "../../App";
import type { ChatThread } from "../../api/client";
import type { ExternalFileDrop, ExternalMentionDrop } from "../../lib/externalInputs";
import { filesFromDataTransfer, hasFileDropData } from "../../lib/fileDropAttachments";
import { hasStorageReferenceDragData, storageReferenceMentionItemsFromDataTransfer } from "../../lib/storageDragReferences";
import { isThreadBusy, isThreadUnread } from "../chat-sidebar/sections";
import { FloatingLauncher } from "./FloatingLauncher";
import { FloatingThreadMenu } from "./FloatingThreadMenu";
import type { FloatingChatWindow } from "./floatingState";

export function FloatingWindow({
  onClose,
  onCollapseChange,
  onCreateDraftChat,
  onMarkThreadRead,
  onRemoveThread,
  onRenameThread,
  onSelectThread,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  threads,
  windowItem,
}: {
  onClose: (windowId: string) => void;
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onRemoveThread: (windowId: string, thread: ChatThread) => Promise<void>;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
}) {
  const [externalFileDrop, setExternalFileDrop] = useState<ExternalFileDrop | null>(null);
  const [externalMentionDrop, setExternalMentionDrop] = useState<ExternalMentionDrop | null>(null);
  const activeThread = threads.find((thread) => thread.thread_id === windowItem.threadId) || null;
  const isActiveThreadBusy = Boolean(activeThread && isThreadBusy(activeThread));
  const isActiveThreadUnread = Boolean(activeThread && isThreadUnread(activeThread));

  function openCollapsedThread() {
    onCollapseChange(windowItem.id, false);
    if (activeThread) {
      void onMarkThreadRead(activeThread);
    }
  }

  function handleFloatingDragOver(event: DragEvent<HTMLElement>) {
    if (!hasStorageReferenceDragData(event.dataTransfer) && !hasFileDropData(event.dataTransfer)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleFloatingDrop(event: DragEvent<HTMLElement>) {
    if (!hasStorageReferenceDragData(event.dataTransfer)) {
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
    const items = storageReferenceMentionItemsFromDataTransfer(event.dataTransfer);
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
      <FloatingLauncher
        isActiveThreadBusy={isActiveThreadBusy}
        isActiveThreadUnread={isActiveThreadUnread}
        onDragOver={handleFloatingDragOver}
        onDrop={handleFloatingDrop}
        onOpen={openCollapsedThread}
        windowItem={windowItem}
      />
      <section
        className={`chat-floating-widget-shell ${windowItem.isCollapsed ? "is-hidden" : ""}`}
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
              onMarkThreadRead={onMarkThreadRead}
              onRemoveThread={onRemoveThread}
              onRenameThread={onRenameThread}
              onSelectThread={onSelectThread}
              threads={threads}
              windowItem={windowItem}
            />
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
          </div>
        </header>
        <div className="chat-floating-widget-shell__body">
          <App
            enablePageCapture
            externalFileDrop={externalFileDrop}
            externalMentionDrop={externalMentionDrop}
            navigationScope={windowItem.id}
            newChatProjectId={windowItem.draftProjectId}
            newChatRequestId={windowItem.isDraft && !windowItem.threadId ? windowItem.id : null}
            runtimeThreads={threads}
            runtimeThreadsError={runtimeThreadsError}
            runtimeThreadsLoaded={runtimeThreadsLoaded}
            threadId={windowItem.threadId}
          />
        </div>
      </section>
    </>
  );
}
