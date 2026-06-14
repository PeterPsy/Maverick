import type { PointerEvent as ReactPointerEvent } from "react";
import type { ChatProject, ChatThread } from "../../api/client";
import { BusyChatGlow } from "../BusyChatGlow";
import { isThreadBusy, isThreadTitlePending, isThreadUnread } from "./sections";
import { ThreadInlineActions } from "./ThreadInlineActions";

export function ThreadRow({
  activeThreadId,
  expandedThreadId,
  expandedThreadTitle,
  isSelected,
  onCloseExpandedThread,
  onMoveThread,
  onRemoveThread,
  onRenameThread,
  onSelectThreadClick,
  onSelectThreadPointer,
  onSetExpandedThreadTitle,
  onToggleThreadEdit,
  onToggleThreadSelection,
  onTrackThreadTouchStart,
  projects,
  sectionProjectId,
  sectionTitle,
  thread,
}: {
  activeThreadId: string | null;
  expandedThreadId: string | null;
  expandedThreadTitle: string;
  isSelected: boolean;
  onCloseExpandedThread: () => void;
  onMoveThread: (thread: ChatThread, projectId: string | null) => Promise<void>;
  onRemoveThread: (threadId: string) => Promise<void>;
  onRenameThread: (threadId: string, title: string, projectId: string | null) => Promise<void>;
  onSelectThreadClick: (thread: ChatThread) => void;
  onSelectThreadPointer: (event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) => void;
  onSetExpandedThreadTitle: (title: string) => void;
  onToggleThreadEdit: (thread: ChatThread) => void;
  onToggleThreadSelection: (thread: ChatThread) => void;
  onTrackThreadTouchStart: (event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) => void;
  projects: ChatProject[];
  sectionProjectId: string | null;
  sectionTitle: string;
  thread: ChatThread;
}) {
  const isBusy = isThreadBusy(thread);
  const isUnread = isThreadUnread(thread);
  const isExpanded = expandedThreadId === thread.thread_id;
  const isTitlePending = isThreadTitlePending(thread);
  const threadLabel = isTitlePending ? "chat" : thread.title || "chat";

  return (
    <div
      className={`bs-chat-list__item ${activeThreadId === thread.thread_id ? "is-active" : ""} ${isBusy ? "is-busy" : ""} ${
        isUnread ? "is-unread" : ""
      } ${isExpanded ? "is-expanded" : ""} ${isSelected ? "is-selected" : ""}`}
    >
      {isBusy ? <BusyChatGlow /> : null}
      <div className="bs-chat-list__select">
        {isExpanded ? (
          <span className="bs-chat-list__title-input-frame">
            <input
              aria-label={`Edit title ${threadLabel}`}
              autoFocus
              className="bs-chat-list__title-input"
              onChange={(event) => onSetExpandedThreadTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  onCloseExpandedThread();
                }
              }}
              value={expandedThreadTitle}
            />
          </span>
        ) : (
          <button
            className="bs-chat-list__select-button"
            onClick={() => onSelectThreadClick(thread)}
            onPointerDown={(event) => onTrackThreadTouchStart(event, thread)}
            onPointerUp={(event) => onSelectThreadPointer(event, thread)}
            type="button"
          >
            <div className="bs-chat-list__row">
              <div className="bs-chat-list__copy">
                {isTitlePending ? (
                  <span aria-label="Generating chat title" className="bs-chat-list__title-skeleton" role="status" />
                ) : (
                  <p className="bs-chat-list__title" title={thread.title}>
                    {thread.title}
                  </p>
                )}
              </div>
            </div>
          </button>
        )}
      </div>
      <div className="bs-chat-list__actions">
        <button
          aria-label={`${isSelected ? "Deselect" : "Select"} ${threadLabel}`}
          aria-pressed={isSelected}
          className="bs-chat-list__selection-toggle"
          onClick={() => onToggleThreadSelection(thread)}
          title={isSelected ? "Deselect chat" : "Select chat"}
          type="button"
        >
          <span aria-hidden="true" className="bs-chat-list__selection-ring" />
        </button>
        {sectionProjectId !== thread.project_id ? (
          <button
            aria-label={`Move ${threadLabel} to ${sectionTitle}`}
            className="bs-instance-menu__trigger"
            onClick={() => void onMoveThread(thread, sectionProjectId)}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              drive_file_move
            </span>
          </button>
        ) : (
          <button
            aria-expanded={isExpanded}
            aria-label={`Edit ${threadLabel}`}
            className="bs-instance-menu__trigger"
            disabled={isTitlePending}
            onClick={() => onToggleThreadEdit(thread)}
            title={isTitlePending ? "Title generation pending" : "Edit chat"}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              more_horiz
            </span>
          </button>
        )}
      </div>
      {isExpanded ? (
        <ThreadInlineActions
          onClose={onCloseExpandedThread}
          onDeleteThread={onRemoveThread}
          onRenameThread={onRenameThread}
          projects={projects}
          title={expandedThreadTitle}
          thread={thread}
        />
      ) : null}
    </div>
  );
}
