import { createRoot } from "react-dom/client";
import { applyInitialMaverickTheme, listenForMaverickThemeMessages } from "../../lib/shellTheme";
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
      {sidebar.error ? <p className="bs-chat-folder__empty">{sidebar.error}</p> : null}

      <div className="bs-chat-sidebar-search-frame">
        <span aria-hidden="true" className="material-symbols-rounded">
          search
        </span>
        <input
          aria-label="Search chats"
          className="bs-chat-sidebar-search"
          onChange={(event) => sidebar.setSearchQuery(event.target.value)}
          placeholder="Search chats"
          value={sidebar.searchQuery}
        />
      </div>

      <div className="bs-chat-list">
        {sidebar.isInitialLoading ? (
          <ChatSidebarSkeleton />
        ) : (
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
              onAddProject={sidebar.addProject}
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
        )}
      </div>
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(<ChatSidebarWidget />);
