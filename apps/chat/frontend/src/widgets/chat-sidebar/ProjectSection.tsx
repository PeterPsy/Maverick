import {
  useId,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { SidebarDisclosure } from "../../components/ui/dashboard-sidebar";
import { ProjectSectionHeader } from "./ProjectSectionHeader";
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
  isShellMobileLayout,
  multiAgentThreadIds,
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
  onTrackThreadTouchCancel,
  onTrackThreadTouchMove,
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
  isShellMobileLayout: boolean;
  multiAgentThreadIds: ReadonlySet<string>;
  onCancelProjectDeletion: () => void;
  onCancelProjectEdit: () => void;
  onCloseExpandedThread: () => void;
  onConfirmProjectDeletion: (projectId: string) => Promise<void>;
  onCreateChat: (projectId?: string | null) => Promise<void>;
  onMoveThread: (thread: ChatThread, projectId: string | null) => Promise<void>;
  onRemoveEditingProject: (projectId: string) => void;
  onRemoveThread: (threadId: string) => Promise<void>;
  onRenameThread: (
    threadId: string,
    title: string,
    projectId: string | null,
  ) => Promise<void>;
  onSaveProjectEdit: () => Promise<void>;
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
  onSetEditingProjectName: (name: string) => void;
  onSetExpandedThreadTitle: (title: string) => void;
  onStartProjectEdit: (project: ChatProject) => void;
  onToggleSection: (sectionId: string) => void;
  onToggleThreadEdit: (thread: ChatThread) => void;
  onToggleThreadSelection: (thread: ChatThread) => void;
  onTrackThreadTouchStart: (
    event: ReactPointerEvent<HTMLButtonElement>,
    thread: ChatThread,
  ) => void;
  pendingProjectDeletion: PendingProjectDeletion | null;
  projects: ChatProject[];
  section: FolderSection;
  selectedThreadIds: ReadonlySet<string>;
}) {
  const disclosureId = useId();
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
      <ProjectSectionHeader
        collapsed={collapsed}
        disclosureId={disclosureId}
        editingName={editingName}
        isEditingProject={isEditingProject}
        isPending={isPending}
        onCancelProjectEdit={onCancelProjectEdit}
        onCreateChat={onCreateChat}
        onRemoveEditingProject={onRemoveEditingProject}
        onSaveProjectEdit={onSaveProjectEdit}
        onSetEditingProjectName={onSetEditingProjectName}
        onStartProjectEdit={onStartProjectEdit}
        onToggleSection={onToggleSection}
        projects={projects}
        section={section}
      />
      {pendingProjectDeletion?.projectId === section.projectId ? (
        <ProjectDeleteConfirm
          isPending={isPending}
          onCancel={onCancelProjectDeletion}
          onConfirm={onConfirmProjectDeletion}
          pendingDeletion={pendingProjectDeletion}
        />
      ) : null}
      <SidebarDisclosure id={disclosureId} open={!collapsed}>
        <div className="bs-chat-folder__dropzone">
          {section.items.length ? (
            section.items.map((thread) => (
              <ThreadRow
                activeThreadId={activeThreadId}
                expandedThreadId={expandedThreadId}
                expandedThreadTitle={expandedThreadTitle}
                isSelected={selectedThreadIds.has(thread.thread_id)}
                isShellMobileLayout={isShellMobileLayout}
                key={thread.thread_id}
                multiAgentThreadIds={multiAgentThreadIds}
                onCloseExpandedThread={onCloseExpandedThread}
                onMoveThread={onMoveThread}
                onRemoveThread={onRemoveThread}
                onRenameThread={onRenameThread}
                onSelectThreadClick={onSelectThreadClick}
                onSelectThreadPointer={onSelectThreadPointer}
                onTrackThreadTouchCancel={onTrackThreadTouchCancel}
                onTrackThreadTouchMove={onTrackThreadTouchMove}
                onSetExpandedThreadTitle={onSetExpandedThreadTitle}
                onToggleThreadEdit={onToggleThreadEdit}
                onToggleThreadSelection={onToggleThreadSelection}
                onTrackThreadTouchStart={onTrackThreadTouchStart}
                canMoveThread={section.canMoveThreads}
                projects={projects}
                sectionProjectId={section.projectId}
                sectionTitle={section.title}
                thread={thread}
              />
            ))
          ) : (
            <p className="bs-chat-folder__empty">{section.emptyLabel}</p>
          )}
        </div>
      </SidebarDisclosure>
    </section>
  );
}
