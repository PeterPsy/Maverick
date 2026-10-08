import { createRoot } from "react-dom/client";
import { ChevronsDownUp, ChevronsUpDown, FolderPlus } from "lucide-react";
import { SidebarNav } from "../../components/ui/dashboard-sidebar";
import { chatNavigationGroups } from "./navigation";
import type { ThreadFilter } from "./sections";
import {
  applyInitialMaverickTheme,
  listenForMaverickThemeMessages,
} from "../../lib/shellTheme";
import { ChatSidebarSkeleton } from "./ChatSidebarSkeleton";
import { ProjectSection } from "./ProjectSection";
import "./styles.css";
import { useChatSidebarState } from "./useChatSidebarState";

applyInitialMaverickTheme();
listenForMaverickThemeMessages();

function ChatSidebarWidget() {
  const sidebar = useChatSidebarState();

  return (
    <main
      className={`bs-widget-root ${sidebar.isShellMobileLayout ? "is-shell-mobile" : ""} ${
        sidebar.hasThreadSelection ? "has-thread-selection" : ""
      } ${sidebar.areThreadActionsRevealed ? "has-thread-actions-revealed" : ""}`}
    >
      {sidebar.error ? (
        <div className="bs-chat-sidebar-error" role="alert">
          <p className="bs-chat-folder__empty">{sidebar.error}</p>
          {sidebar.projectsError ? (
            <button
              className="bs-chat-sidebar-project-retry"
              disabled={sidebar.isProjectsLoading}
              onClick={() => void sidebar.refreshProjects()}
              type="button"
            >
              {sidebar.isProjectsLoading
                ? "Loading projects…"
                : "Reload project names"}
            </button>
          ) : null}
        </div>
      ) : null}

      <SidebarNav
        actions={
          <>
            <button
              aria-label={
                sidebar.areAllSectionsCollapsed
                  ? "Expand all projects"
                  : "Collapse all projects"
              }
              className="dashboard-sidebar__icon-button"
              disabled={!sidebar.sections.length}
              onClick={sidebar.toggleAllSections}
              type="button"
            >
              {sidebar.areAllSectionsCollapsed ? (
                <ChevronsUpDown size={15} />
              ) : (
                <ChevronsDownUp size={15} />
              )}
            </button>
            <button
              aria-label="New project"
              className="dashboard-sidebar__icon-button"
              disabled={sidebar.isPending}
              onClick={() => void sidebar.addProject()}
              type="button"
            >
              <FolderPlus size={16} />
            </button>
          </>
        }
        activeId={sidebar.threadFilter}
        groups={chatNavigationGroups(sidebar.threadFilterCounts)}
        onSearchChange={sidebar.setSearchQuery}
        onSelect={(id) => sidebar.setThreadFilter(id as ThreadFilter)}
        searchQuery={sidebar.searchQuery}
      >
        <div className="bs-chat-list">
          {sidebar.isInitialLoading ? (
            <ChatSidebarSkeleton />
          ) : sidebar.sections.length ? (
            sidebar.sections.map((section) => (
              <ProjectSection
                activeThreadId={sidebar.activeThreadId}
                collapsed={sidebar.collapsedSections[section.id] ?? false}
                editingProject={sidebar.editingProject}
                editingProjectRef={sidebar.editingProjectRef}
                expandedThreadId={sidebar.expandedThreadId}
                expandedThreadTitle={sidebar.expandedThreadTitle}
                isPending={sidebar.isPending}
                key={section.id}
                multiAgentThreadIds={sidebar.multiAgentThreadIds}
                onCancelProjectDeletion={sidebar.cancelProjectDeletion}
                onCancelProjectEdit={sidebar.cancelProjectEdit}
                onCloseExpandedThread={sidebar.closeExpandedThread}
                onConfirmProjectDeletion={sidebar.confirmProjectDeletion}
                onCreateChat={sidebar.createChat}
                onMoveThread={sidebar.moveThread}
                onRemoveEditingProject={sidebar.removeEditingProject}
                onRemoveThread={sidebar.removeThread}
                onRenameThread={sidebar.renameThread}
                onSaveProjectEdit={sidebar.saveProjectEdit}
                onSelectThreadClick={sidebar.selectThreadFromClick}
                onSelectThreadPointer={sidebar.selectThreadFromPointer}
                onTrackThreadTouchCancel={sidebar.cancelThreadTouch}
                onTrackThreadTouchMove={sidebar.trackThreadTouchMove}
                onSetEditingProjectName={sidebar.setEditingProjectName}
                onSetExpandedThreadTitle={sidebar.setExpandedThreadTitle}
                onStartProjectEdit={sidebar.startProjectEdit}
                onToggleSection={sidebar.toggleSection}
                onToggleThreadEdit={sidebar.toggleThreadEdit}
                onToggleThreadSelection={sidebar.toggleThreadSelection}
                onTrackThreadTouchStart={sidebar.trackThreadTouchStart}
                pendingProjectDeletion={sidebar.pendingProjectDeletion}
                projects={sidebar.projects}
                section={section}
                selectedThreadIds={sidebar.selectedThreadIds}
              />
            ))
          ) : (
            <p className="bs-chat-folder__empty">No chats match this filter.</p>
          )}
        </div>
      </SidebarNav>
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(
  <ChatSidebarWidget />,
);
