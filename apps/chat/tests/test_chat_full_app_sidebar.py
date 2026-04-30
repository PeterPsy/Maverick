from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_ROOT = REPO_ROOT / "apps" / "chat"


class ChatFullAppSidebarTests(unittest.TestCase):
    def test_chat_app_sidebar_is_full_app_only(self) -> None:
        app_source = (CHAT_ROOT / "frontend" / "src" / "App.tsx").read_text()
        layout_source = (CHAT_ROOT / "frontend" / "src" / "styles" / "chat" / "layout.css").read_text()
        floating_widget_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-floating" / "main.tsx").read_text()
        sidebar_widget_source = (CHAT_ROOT / "frontend" / "src" / "widgets" / "chat-sidebar" / "main.tsx").read_text()

        self.assertIn("const showAppSidebar = !navigationScope", app_source)
        self.assertIn("showAppSidebar ? (", app_source)
        self.assertIn("<ChatAppSidebar", app_source)
        self.assertIn('aria-label="Chat list"', app_source)
        self.assertIn("onSelectThread={(thread) =>", app_source)
        self.assertIn("void handleSelectThread(thread)", app_source)
        self.assertIn("void createChat()", app_source)
        self.assertIn("deleteThread,", app_source)
        self.assertIn("renameSidebarThread", app_source)
        self.assertIn("deleteSidebarThread", app_source)
        self.assertIn("deleteAllSidebarThreads", app_source)
        self.assertIn("setDeleteProgress", app_source)
        self.assertIn("role=\"progressbar\"", app_source)
        self.assertIn('aria-label="Delete all chats"', app_source)
        self.assertIn("chatapp-app-sidebar__actions", app_source)
        self.assertIn("chatapp-app-sidebar__header-actions", app_source)
        self.assertIn("chatapp-app-sidebar__rename-form", app_source)
        self.assertIn(".chatapp-root--with-sidebar", layout_source)
        self.assertIn(".chatapp-app-sidebar", layout_source)
        self.assertIn(".chatapp-app-sidebar__thread:hover .chatapp-app-sidebar__actions", layout_source)
        self.assertIn(".chatapp-app-sidebar__thread:focus-within .chatapp-app-sidebar__actions", layout_source)
        self.assertIn(".chatapp-app-sidebar__header-actions button.is-danger", layout_source)
        self.assertIn(".chatapp-app-sidebar__rename-form", layout_source)
        self.assertIn(".chatapp-delete-dialog__progress-track", layout_source)
        self.assertNotIn("ChatAppSidebar", floating_widget_source)
        self.assertNotIn("chatapp-app-sidebar", floating_widget_source)
        self.assertNotIn("ChatAppSidebar", sidebar_widget_source)
        self.assertNotIn("chatapp-app-sidebar", sidebar_widget_source)


if __name__ == "__main__":
    unittest.main()
