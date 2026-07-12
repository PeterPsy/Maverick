from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_ROOT = REPO_ROOT / "apps" / "chat"


class ChatFullAppSidebarTests(unittest.TestCase):
    def test_chat_thread_lists_are_widget_owned(self) -> None:
        app_source = (CHAT_ROOT / "frontend" / "src" / "App.tsx").read_text()
        navigation_source = (CHAT_ROOT / "frontend" / "src" / "hooks" / "useChatNavigation.ts").read_text()
        layout_source = (CHAT_ROOT / "frontend" / "src" / "styles" / "chat" / "layout.css").read_text()
        floating_widget_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-floating" / "main.tsx").read_text()
        sidebar_widget_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "main.tsx").read_text()
        sidebar_state_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "useChatSidebarState.ts").read_text()
        sidebar_project_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "useSidebarProjectActions.ts").read_text()
        project_section_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "ProjectSection.tsx").read_text()
        project_utils_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "chatSidebarStateUtils.ts").read_text()

        self.assertNotIn("ChatAppSidebar", app_source)
        self.assertNotIn("chatapp-app-sidebar", app_source)
        self.assertNotIn("deleteThread,", app_source)
        self.assertIn("navigationScope?: string", app_source)
        self.assertIn("newChatProjectId?: string | null", app_source)
        self.assertIn("newChatRequestId?: string | null", app_source)
        self.assertIn("threadId?: string | null", app_source)
        self.assertIn("handleNavigationParams", navigation_source)
        self.assertNotIn(".chatapp-root--with-sidebar", layout_source)
        self.assertNotIn(".chatapp-app-sidebar", layout_source)
        self.assertIn("deleteThread,", sidebar_state_source)
        self.assertIn("updateThread,", sidebar_state_source)
        self.assertIn("renameThread", sidebar_state_source)
        self.assertIn("removeThread", sidebar_state_source)
        self.assertIn("moveThread", sidebar_state_source)
        self.assertIn("createProject", sidebar_project_source)
        self.assertIn("renameProject", sidebar_project_source)
        self.assertIn("deleteProject", sidebar_project_source)
        self.assertNotIn("window.confirm", sidebar_state_source + sidebar_project_source + project_section_source)
        self.assertIn("pendingProjectDeletion", project_section_source)
        self.assertIn("This action cannot be undone.", project_utils_source)
        self.assertIn("ChatSidebarWidget", sidebar_widget_source)
        self.assertNotIn("ChatAppSidebar", floating_widget_source)
        self.assertNotIn("chatapp-app-sidebar", floating_widget_source)
        self.assertNotIn("ChatAppSidebar", sidebar_widget_source)
        self.assertNotIn("chatapp-app-sidebar", sidebar_widget_source)

    def test_first_draft_send_queues_turn_before_thread_navigation(self) -> None:
        submission_source = (CHAT_ROOT / "frontend" / "src" / "hooks" / "useMessageSubmission.ts").read_text()
        submit_start = submission_source.index("async function submitMessage")
        first_draft_turn = submission_source.index("createRuntimeSessionWithTurn({", submit_start)
        send_turn = submission_source.index("sendRuntimeTurn(", submit_start)
        thread_navigation = submission_source.index("openChatThreadRouteInShell(optimisticThread.thread_id", submit_start)

        self.assertLess(first_draft_turn, thread_navigation)
        self.assertLess(send_turn, thread_navigation)
        self.assertIn("createRuntimeSessionWithTurn", submission_source)
        self.assertNotIn("thread = await createChat", submission_source)


if __name__ == "__main__":
    unittest.main()
