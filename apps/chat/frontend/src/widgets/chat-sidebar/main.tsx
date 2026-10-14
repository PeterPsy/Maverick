import { createRoot } from "react-dom/client";
import {
  applyInitialMaverickTheme,
  listenForMaverickThemeMessages,
} from "../../lib/shellTheme";
import { ChatConversationPanel } from "./ChatConversationPanel";
import "./styles.css";
import { useChatSidebarState } from "./useChatSidebarState";
import { ScheduledSidebar } from "./ScheduledSidebar";

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
      <div className="bs-chat-sidebar-sections">
        <ChatConversationPanel sidebar={sidebar} />
        <ScheduledSidebar mobile={sidebar.isShellMobileLayout} />
      </div>
    </main>
  );
}

createRoot(document.getElementById("chat-sidebar-root") as HTMLElement).render(
  <ChatSidebarWidget />,
);
