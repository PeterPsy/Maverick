import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Check, FolderInput, Pencil } from "lucide-react";
import type { ChatProject, ChatThread } from "../../api/client";
import {
  attachChatThreadDragImage,
  chatThreadDragPayload,
  writeChatThreadDragData,
} from "../../lib/chatThreadDragReferences";
import { BusyChatGlow } from "../BusyChatGlow";
import {
  isThreadBusy,
  isThreadTitlePending,
  isThreadUnread,
  threadSourceBadges,
} from "./sections";
import { ThreadEditor } from "./ThreadEditor";
import { ThreadSourceIcon } from "./ThreadSourceIcon";
import {
  formatThreadLastMessageTimestamp,
  threadLastMessageIso,
} from "./threadTimestamps";

export function ThreadRow({
  activeThreadId,
  expandedThreadId,
  expandedThreadTitle,
  isSelected,
  isShellMobileLayout,
  multiAgentThreadIds,
  onCloseExpandedThread,
  onMoveThread,
  onRemoveThread,
  onRenameThread,
  onSelectThreadClick,
  onSelectThreadPointer,
  onTrackThreadTouchCancel,
  onTrackThreadTouchMove,
  onSetExpandedThreadTitle,
  onToggleThreadEdit,
  onToggleThreadSelection,
  onTrackThreadTouchStart,
  canMoveThread,
  projects,
  sectionProjectId,
  sectionTitle,
  thread,
}: {
  activeThreadId: string | null;
  expandedThreadId: string | null;
  expandedThreadTitle: string;
  isSelected: boolean;
  isShellMobileLayout: boolean;
  multiAgentThreadIds: ReadonlySet<string>;
  onCloseExpandedThread: () => void;
  onMoveThread: (thread: ChatThread, projectId: string | null) => Promise<void>;
  onRemoveThread: (threadId: string) => Promise<void>;
  onRenameThread: (
    threadId: string,
    title: string,
    projectId: string | null,
  ) => Promise<void>;
  onSelectThreadClick: (thread: ChatThread) => void;
  onSelectThreadPointer: (
    event: ReactPointerEvent<HTMLButtonElement>,
    thread: ChatThread,
  ) => void;
  onTrackThreadTouchCancel: (
    event: ReactPointerEvent<HTMLButtonElement>,
    thread: ChatThread,
  ) => void;
  onTrackThreadTouchMove: (
    event: ReactPointerEvent<HTMLButtonElement>,
    thread: ChatThread,
  ) => void;
  onSetExpandedThreadTitle: (title: string) => void;
  onToggleThreadEdit: (thread: ChatThread) => void;
  onToggleThreadSelection: (thread: ChatThread) => void;
  onTrackThreadTouchStart: (
    event: ReactPointerEvent<HTMLButtonElement>,
    thread: ChatThread,
  ) => void;
  canMoveThread: boolean;
  projects: ChatProject[];
  sectionProjectId: string | null;
  sectionTitle: string;
  thread: ChatThread;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const isBusy = isThreadBusy(thread);
  const isUnread = isThreadUnread(thread);
  const isExpanded = expandedThreadId === thread.thread_id;
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const wasEditingRef = useRef(isExpanded);
  const isTitlePending = isThreadTitlePending(thread);
  const threadLabel = isTitlePending ? "chat" : thread.title || "chat";
  const lastMessageTimestamp = formatThreadLastMessageTimestamp(thread);
  const lastMessageIso = threadLastMessageIso(thread);
  const sourceBadges = threadSourceBadges(thread, multiAgentThreadIds);

  useEffect(() => {
    if (
      wasEditingRef.current &&
      !isExpanded &&
      document.activeElement === document.body
    )
      editButtonRef.current?.focus();
    wasEditingRef.current = isExpanded;
  }, [isExpanded]);

  function handleDragStart(event: DragEvent<HTMLDivElement>) {
    if (isExpanded) {
      event.preventDefault();
      return;
    }
    writeChatThreadDragData(event.dataTransfer, chatThreadDragPayload(thread));
    attachChatThreadDragImage(event, threadLabel);
    setIsDragging(true);
    if (isShellMobileLayout) {
      window.parent.postMessage({ type: "maverick.shell.sidebar.close" }, "*");
    }
  }

  return (
    <div
      className={`bs-chat-list__item ${activeThreadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""} ${
        isUnread ? "is-unread" : ""
      } ${isExpanded ? "is-expanded" : ""} ${isSelected ? "is-selected" : ""} ${isDragging ? "is-dragging" : ""}`}
      draggable={!isExpanded}
      onDragEnd={() => setIsDragging(false)}
      onDragStart={handleDragStart}
    >
      {isBusy ? <BusyChatGlow /> : null}
      {isExpanded ? (
        <ThreadEditor
          onClose={onCloseExpandedThread}
          onDeleteThread={onRemoveThread}
          onRenameThread={onRenameThread}
          onTitleChange={onSetExpandedThreadTitle}
          projects={projects}
          title={expandedThreadTitle}
          thread={thread}
        />
      ) : (
        <>
          <div className="bs-chat-list__select">
            <button
              aria-current={
                activeThreadId === thread.thread_id ? "page" : undefined
              }
              className="bs-chat-list__select-button"
              onClick={() => onSelectThreadClick(thread)}
              onPointerCancel={(event) =>
                onTrackThreadTouchCancel(event, thread)
              }
              onPointerDown={(event) => onTrackThreadTouchStart(event, thread)}
              onPointerMove={(event) => onTrackThreadTouchMove(event, thread)}
              onPointerUp={(event) => onSelectThreadPointer(event, thread)}
              title={`Open ${threadLabel}. Drag to a composer to reference this chat.`}
              type="button"
            >
              <div className="bs-chat-list__row">
                <div className="bs-chat-list__copy">
                  {isTitlePending ? (
                    <span
                      aria-label="Generating chat title"
                      className="bs-chat-list__title-skeleton"
                      role="status"
                    />
                  ) : (
                    <p className="bs-chat-list__title" title={thread.title}>
                      {thread.title}
                    </p>
                  )}
                </div>
                {sourceBadges.length ? (
                  <span className="bs-chat-list__source-badges">
                    {sourceBadges.map((badge) => (
                      <span
                        className="bs-chat-list__source-badge"
                        key={badge.kind}
                        title={badge.label}
                      >
                        <ThreadSourceIcon kind={badge.kind} />
                      </span>
                    ))}
                  </span>
                ) : null}
              </div>
            </button>
          </div>
          <div className="bs-chat-list__trailing">
            {lastMessageTimestamp ? (
              <span className="bs-chat-list__meta">
                <time
                  className="bs-chat-list__timestamp"
                  dateTime={lastMessageIso}
                  title={`Last message ${lastMessageTimestamp}`}
                >
                  {lastMessageTimestamp}
                </time>
              </span>
            ) : null}
            <div className="bs-chat-list__actions">
              <button
                aria-label={`${isSelected ? "Deselect" : "Select"} ${threadLabel}`}
                aria-pressed={isSelected}
                className="bs-chat-list__selection-toggle"
                onClick={() => onToggleThreadSelection(thread)}
                title={isSelected ? "Deselect chat" : "Select chat"}
                type="button"
              >
                <span
                  aria-hidden="true"
                  className="bs-chat-list__selection-ring"
                >
                  {isSelected ? <Check size={11} strokeWidth={2.5} /> : null}
                </span>
              </button>
              {canMoveThread && sectionProjectId !== thread.project_id ? (
                <button
                  aria-label={`Move ${threadLabel} to ${sectionTitle}`}
                  className="bs-instance-menu__trigger"
                  onClick={() => void onMoveThread(thread, sectionProjectId)}
                  type="button"
                >
                  <FolderInput aria-hidden="true" size={16} />
                </button>
              ) : (
                <button
                  aria-label={`Edit ${threadLabel}`}
                  className="bs-instance-menu__trigger"
                  disabled={isTitlePending}
                  onClick={() => onToggleThreadEdit(thread)}
                  ref={editButtonRef}
                  title={
                    isTitlePending ? "Title generation pending" : "Edit chat"
                  }
                  type="button"
                >
                  <Pencil aria-hidden="true" size={15} strokeWidth={1.5} />
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
