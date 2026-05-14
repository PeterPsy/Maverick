from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_ROOT = REPO_ROOT / "apps" / "chat"


class ChatFullAppSidebarTests(unittest.TestCase):
    def test_chat_thread_lists_are_widget_owned(self) -> None:
        app_source = (CHAT_ROOT / "frontend" / "src" / "App.tsx").read_text()
        layout_source = (CHAT_ROOT / "frontend" / "src" / "styles" / "chat" / "layout.css").read_text()
        floating_widget_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-floating" / "main.tsx").read_text()
        sidebar_widget_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "main.tsx").read_text()

        self.assertNotIn("ChatAppSidebar", app_source)
        self.assertNotIn("chatapp-app-sidebar", app_source)
        self.assertNotIn("deleteThread,", app_source)
        self.assertIn("navigationScope?: string", app_source)
        self.assertIn("newChatProjectId?: string | null", app_source)
        self.assertIn("newChatRequestId?: string | null", app_source)
        self.assertIn("threadId?: string | null", app_source)
        self.assertIn("handleNavigationParams", app_source)
        self.assertNotIn(".chatapp-root--with-sidebar", layout_source)
        self.assertNotIn(".chatapp-app-sidebar", layout_source)
        self.assertIn("deleteThread,", sidebar_widget_source)
        self.assertIn("updateThread,", sidebar_widget_source)
        self.assertIn("renameThread", sidebar_widget_source)
        self.assertIn("removeThread", sidebar_widget_source)
        self.assertIn("moveThread", sidebar_widget_source)
        self.assertIn("createProject", sidebar_widget_source)
        self.assertIn("renameProject", sidebar_widget_source)
        self.assertIn("deleteProject", sidebar_widget_source)
        self.assertNotIn("window.confirm", sidebar_widget_source)
        self.assertIn("pendingProjectDeletion", sidebar_widget_source)
        self.assertIn("This action cannot be undone.", sidebar_widget_source)
        self.assertIn("ChatSidebarWidget", sidebar_widget_source)
        self.assertNotIn("ChatAppSidebar", floating_widget_source)
        self.assertNotIn("chatapp-app-sidebar", floating_widget_source)
        self.assertNotIn("ChatAppSidebar", sidebar_widget_source)
        self.assertNotIn("chatapp-app-sidebar", sidebar_widget_source)

    def test_first_draft_send_queues_turn_before_thread_navigation(self) -> None:
        app_source = (CHAT_ROOT / "frontend" / "src" / "App.tsx").read_text()
        submit_start = app_source.index("async function submitMessage")
        first_draft_turn = app_source.index("response = await createRuntimeSessionWithTurn", submit_start)
        send_turn = app_source.index("response = await sendRuntimeTurn", submit_start)
        thread_navigation = app_source.index("openChatThreadRouteInShell(optimisticThread.thread_id", submit_start)

        self.assertLess(first_draft_turn, thread_navigation)
        self.assertLess(send_turn, thread_navigation)
        self.assertIn("createRuntimeSessionWithTurn", app_source)
        self.assertNotIn("thread = await createChat", app_source)


if __name__ == "__main__":
    unittest.main()
