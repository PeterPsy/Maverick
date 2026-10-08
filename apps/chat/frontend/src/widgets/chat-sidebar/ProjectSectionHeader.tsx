import {
  Check,
  ChevronRight,
  Folder,
  FolderOpen,
  Inbox,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import type { ChatProject } from "../../api/client";
import { SidebarActionMenu } from "../../components/ui/dashboard-sidebar";
import { isThreadBusy, isThreadUnread, type FolderSection } from "./sections";

export function ProjectSectionHeader({
  collapsed,
  disclosureId,
  editingName,
  isEditingProject,
  isPending,
  onCancelProjectEdit,
  onCreateChat,
  onRemoveEditingProject,
  onSaveProjectEdit,
  onSetEditingProjectName,
  onStartProjectEdit,
  onToggleSection,
  projects,
  section,
}: {
  collapsed: boolean;
  disclosureId: string;
  editingName: string;
  isEditingProject: boolean;
  isPending: boolean;
  onCancelProjectEdit: () => void;
  onCreateChat: (projectId?: string | null) => Promise<void>;
  onRemoveEditingProject: (projectId: string) => void;
  onSaveProjectEdit: () => Promise<void>;
  onSetEditingProjectName: (name: string) => void;
  onStartProjectEdit: (project: ChatProject) => void;
  onToggleSection: (sectionId: string) => void;
  projects: ChatProject[];
  section: FolderSection;
}) {
  const hasBusyChats = section.items.some(isThreadBusy);
  const hasUnreadChats = section.items.some(isThreadUnread);
  return (
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
        <button
          aria-controls={disclosureId}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? "Show" : "Hide"} chats in project ${section.title}`}
          className={`bs-chat-folder__toggle ${collapsed ? "is-collapsed" : ""}`}
          onClick={() => onToggleSection(section.id)}
          type="button"
        >
          <ChevronRight
            aria-hidden="true"
            className="bs-chat-folder__chevron"
            size={13}
          />
          {section.projectId ? (
            collapsed ? (
              <Folder aria-hidden="true" size={16} />
            ) : (
              <FolderOpen aria-hidden="true" size={16} />
            )
          ) : (
            <Inbox aria-hidden="true" size={16} />
          )}
          <span className="bs-chat-folder__title">{section.title}</span>
          {hasBusyChats || hasUnreadChats ? (
            <span
              aria-label={hasBusyChats ? "Active chats" : "Unread chats"}
              className={`bs-chat-folder__status ${hasBusyChats ? "is-busy" : ""}`}
              role="img"
            />
          ) : null}
          <span className="bs-chat-folder__count">{section.items.length}</span>
        </button>
      )}
      <div className="bs-chat-folder__header-actions">
        {isEditingProject ? (
          <>
            <button
              aria-label={`Save changes to ${section.title}`}
              className="dashboard-sidebar__icon-button"
              disabled={isPending || !editingName.trim()}
              onClick={() => void onSaveProjectEdit()}
              type="button"
            >
              <Check size={15} />
            </button>
            <button
              aria-label="Cancel project changes"
              className="dashboard-sidebar__icon-button"
              disabled={isPending}
              onClick={onCancelProjectEdit}
              type="button"
            >
              <X size={15} />
            </button>
            <button
              aria-label={`Delete project ${section.title}`}
              className="dashboard-sidebar__icon-button"
              disabled={isPending}
              onClick={() => {
                if (section.projectId)
                  onRemoveEditingProject(section.projectId);
              }}
              type="button"
            >
              <Trash2 size={15} />
            </button>
          </>
        ) : section.canManage ? (
          <>
            <button
              aria-label={`New chat in ${section.title}`}
              className="dashboard-sidebar__icon-button"
              disabled={isPending}
              onClick={() => void onCreateChat(section.projectId)}
              type="button"
            >
              <Plus size={15} />
            </button>
            <SidebarActionMenu
              disabled={isPending}
              icon={MoreHorizontal}
              label={`Project actions for ${section.title}`}
              items={[
                {
                  title: "Rename project",
                  icon: Pencil,
                  onSelect: () => {
                    const project = projects.find(
                      (item) => item.project_id === section.projectId,
                    );
                    if (project) onStartProjectEdit(project);
                  },
                },
                {
                  title: "New chat",
                  icon: Plus,
                  onSelect: () => {
                    void onCreateChat(section.projectId);
                  },
                },
                {
                  title: "Delete project",
                  icon: Trash2,
                  danger: true,
                  onSelect: () => {
                    const project = projects.find(
                      (item) => item.project_id === section.projectId,
                    );
                    if (project) {
                      onStartProjectEdit(project);
                      onRemoveEditingProject(project.project_id);
                    }
                  },
                },
              ]}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}
