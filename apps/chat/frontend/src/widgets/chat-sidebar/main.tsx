import { createRoot } from "react-dom/client";
import { Search } from "lucide-react";
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
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search chats"
          className="bs-chat-sidebar-search"
          onChange={(event) => sidebar.setSearchQuery(event.target.value)}
          placeholder="Search chats"
          value={sidebar.searchQuery}
        />
      </div>

      <div aria-label="Chat filters" className="bs-chat-sidebar-source-filter" role="group">
        <button
          aria-pressed={sidebar.threadFilter === "all"}
          className={`bs-chat-sidebar-source-filter__button ${sidebar.threadFilter === "all" ? "is-active" : ""}`}
          onClick={() => sidebar.setThreadFilter("all")}
          type="button"
        >
          <span className="bs-chat-sidebar-source-filter__label">All</span>
          <span className="bs-chat-sidebar-source-filter__count">{sidebar.threadFilterCounts.all}</span>
        </button>
        <button
          aria-label="Senses chats"
          aria-pressed={sidebar.threadFilter === "senses"}
          className={`bs-chat-sidebar-source-filter__button is-label-collapsible ${sidebar.threadFilter === "senses" ? "is-active" : ""}`}
          onClick={() => sidebar.setThreadFilter("senses")}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            sensors
          </span>
          <span className="bs-chat-sidebar-source-filter__label">Senses</span>
          <span className="bs-chat-sidebar-source-filter__count">{sidebar.threadFilterCounts.senses}</span>
        </button>
        <button
          aria-label="Multi-agent chats"
          aria-pressed={sidebar.threadFilter === "multi_agent"}
          className={`bs-chat-sidebar-source-filter__button is-label-collapsible ${sidebar.threadFilter === "multi_agent" ? "is-active" : ""}`}
          onClick={() => sidebar.setThreadFilter("multi_agent")}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            account_tree
          </span>
          <span className="bs-chat-sidebar-source-filter__label">Multi</span>
          <span className="bs-chat-sidebar-source-filter__count">{sidebar.threadFilterCounts.multi_agent}</span>
        </button>
        <button
          aria-label="Unread or active chats"
          aria-pressed={sidebar.threadFilter === "unread"}
          className={`bs-chat-sidebar-source-filter__button is-label-collapsible ${sidebar.threadFilter === "unread" ? "is-active" : ""}`}
          onClick={() => sidebar.setThreadFilter("unread")}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            mark_chat_unread
          </span>
          <span className="bs-chat-sidebar-source-filter__label">Unread</span>
          <span className="bs-chat-sidebar-source-filter__count">{sidebar.threadFilterCounts.unread}</span>
        </button>
      </div>

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
        ) : (
          <p className="bs-chat-folder__empty">No chats match this filter.</p>
        )}
      </div>
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(<ChatSidebarWidget />);
