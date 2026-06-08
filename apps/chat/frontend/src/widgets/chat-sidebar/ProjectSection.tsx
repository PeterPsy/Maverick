import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import type { ChatProject, ChatThread } from "../../api/client";
import { ProjectDeleteConfirm } from "./ProjectDeleteConfirm";
import type { FolderSection } from "./sections";
import { ThreadRow } from "./ThreadRow";
import type { PendingProjectDeletion } from "./useChatSidebarState";

export function ProjectSection({
  activeThreadId,
  collapsed,
  editingProject,
  editingProjectRef,
  expandedThreadId,
  expandedThreadTitle,
  isPending,
  onAddProject,
  onCancelProjectDeletion,
  onCancelProjectEdit,
  onCloseExpandedThread,
  onConfirmProjectDeletion,
  onCreateChat,
  onMoveThread,
  onRemoveEditingProject,
  onRemoveThread,
  onRenameThread,
  onSaveProjectEdit,
  onSelectThreadClick,
  onSelectThreadPointer,
  onSetEditingProjectName,
  onSetExpandedThreadTitle,
  onStartProjectEdit,
  onToggleSection,
  onToggleThreadEdit,
  onToggleThreadSelection,
  onTrackThreadTouchStart,
  pendingProjectDeletion,
  projects,
  section,
  selectedThreadIds,
}: {
  activeThreadId: string | null;
  collapsed: boolean;
  editingProject: { projectId: string; name: string } | null;
  editingProjectRef: RefObject<HTMLElement | null>;
  expandedThreadId: string | null;
  expandedThreadTitle: string;
  isPending: boolean;
  onAddProject: () => Promise<void>;
  onCancelProjectDeletion: () => void;
  onCancelProjectEdit: () => void;
  onCloseExpandedThread: () => void;
  onConfirmProjectDeletion: (projectId: string) => Promise<void>;
  onCreateChat: (projectId?: string | null) => Promise<void>;
  onMoveThread: (thread: ChatThread, projectId: string | null) => Promise<void>;
  onRemoveEditingProject: (projectId: string) => void;
  onRemoveThread: (threadId: string) => Promise<void>;
  onRenameThread: (threadId: string, title: string, projectId: string | null) => Promise<void>;
  onSaveProjectEdit: () => Promise<void>;
  onSelectThreadClick: (thread: ChatThread) => void;
  onSelectThreadPointer: (event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) => void;
  onSetEditingProjectName: (name: string) => void;
  onSetExpandedThreadTitle: (title: string) => void;
  onStartProjectEdit: (project: ChatProject) => void;
  onToggleSection: (sectionId: string) => void;
  onToggleThreadEdit: (thread: ChatThread) => void;
  onToggleThreadSelection: (thread: ChatThread) => void;
  onTrackThreadTouchStart: (event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) => void;
  pendingProjectDeletion: PendingProjectDeletion | null;
  projects: ChatProject[];
  section: FolderSection;
  selectedThreadIds: ReadonlySet<string>;
}) {
  const isEditingProject = editingProject?.projectId === section.projectId;
  const editingName = isEditingProject ? editingProject.name : section.title;

  return (
    <section
      className={`bs-chat-folder ${collapsed ? "is-collapsed" : ""} ${isEditingProject ? "is-project-editing" : ""}`}
      key={section.id}
      ref={(element) => {
        if (isEditingProject) {
          editingProjectRef.current = element;
          return;
        }
        if (editingProjectRef.current === element) {
          editingProjectRef.current = null;
        }
      }}
    >
      <div className="bs-chat-folder__header">
        {isEditingProject ? (
          <span className="bs-chat-folder__title-input-frame">
            <input
              aria-label={`Rename project ${section.title}`}
              autoFocus
              className="bs-chat-folder__title-input"
              onChange={(event) => onSetEditingProjectName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  onCancelProjectEdit();
                }
                if (event.key === "Enter") {
                  event.preventDefault();
                  void onSaveProjectEdit();
                }
              }}
              value={editingName}
            />
          </span>
        ) : (
          <p className="bs-chat-folder__title">{section.title}</p>
        )}
        <div className="bs-chat-folder__header-actions">
          <button
            aria-expanded={!collapsed}
            aria-label={`${collapsed ? "Show" : "Hide"} chats in project ${section.title}`}
            className={`bs-chat-folder__toggle ${collapsed ? "is-collapsed" : ""}`}
            onClick={() => onToggleSection(section.id)}
            type="button"
          >
            <span className="bs-chat-folder__count">{section.items.length}</span>
            <span aria-hidden="true" className="material-symbols-rounded bs-chat-folder__chevron">
              expand_more
            </span>
          </button>
          {section.canManage ? (
            <button
              aria-label={isEditingProject ? `Delete project ${section.title}` : `New chat in ${section.title}`}
              className={`bs-chat-folder__action-button ${isEditingProject ? "is-danger" : ""}`}
              disabled={isPending}
              onClick={() => {
                if (isEditingProject && section.projectId) {
                  onRemoveEditingProject(section.projectId);
                  return;
                }
                void onCreateChat(section.projectId);
              }}
              title={isEditingProject ? "Delete project" : "New chat"}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                {isEditingProject ? "delete" : "add"}
              </span>
            </button>
          ) : null}
          {section.projectId === null ? (
            <button
              aria-label="New project"
              className="bs-chat-folder__action-button"
              disabled={isPending}
              onClick={() => void onAddProject()}
              title="New project"
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                create_new_folder
              </span>
            </button>
          ) : null}
          {section.canManage ? (
            <button
              aria-label={isEditingProject ? `Save changes to ${section.title}` : `Edit project ${section.title}`}
              className="bs-instance-menu__trigger bs-folder-menu__trigger"
              disabled={isPending || (isEditingProject && !editingName.trim())}
              onClick={() => {
                const project = projects.find((item) => item.project_id === section.projectId);
                if (!project) {
                  return;
                }
                if (isEditingProject) {
                  void onSaveProjectEdit();
                  return;
                }
                onStartProjectEdit(project);
              }}
              title={isEditingProject ? "Save" : "Edit project"}
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                {isEditingProject ? "check" : "more_horiz"}
              </span>
            </button>
          ) : null}
        </div>
      </div>
      {pendingProjectDeletion?.projectId === section.projectId ? (
        <ProjectDeleteConfirm
          isPending={isPending}
          onCancel={onCancelProjectDeletion}
          onConfirm={onConfirmProjectDeletion}
          pendingDeletion={pendingProjectDeletion}
        />
      ) : null}
      {!collapsed ? (
        <div className="bs-chat-folder__dropzone">
          {section.items.length ? (
            section.items.map((thread) => (
              <ThreadRow
                activeThreadId={activeThreadId}
                expandedThreadId={expandedThreadId}
                expandedThreadTitle={expandedThreadTitle}
                isSelected={selectedThreadIds.has(thread.thread_id)}
                key={thread.thread_id}
                onCloseExpandedThread={onCloseExpandedThread}
                onMoveThread={onMoveThread}
                onRemoveThread={onRemoveThread}
                onRenameThread={onRenameThread}
                onSelectThreadClick={onSelectThreadClick}
                onSelectThreadPointer={onSelectThreadPointer}
                onSetExpandedThreadTitle={onSetExpandedThreadTitle}
                onToggleThreadEdit={onToggleThreadEdit}
                onToggleThreadSelection={onToggleThreadSelection}
                onTrackThreadTouchStart={onTrackThreadTouchStart}
                projects={projects}
                sectionProjectId={section.projectId}
                sectionTitle={section.title}
                thread={thread}
              />
            ))
          ) : (
            <p className="bs-chat-folder__empty">No chats in this project.</p>
          )}
        </div>
      ) : null}
    </section>
  );
}
