from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class BaseShellAppMountingTests(unittest.TestCase):
    def test_base_shell_uses_persistent_app_frames(self) -> None:
        host_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/AppFrameHost.tsx").read_text()
        workspace_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/WorkspaceView.tsx").read_text()

        self.assertIn("maverick.app.navigate", host_source)
        self.assertIn("maverick.app.ready", host_source)
        self.assertIn("postMessage", host_source)
        self.assertIn("src={app.frontend_mount}", host_source)
        self.assertNotIn("URLSearchParams", workspace_source)
        self.assertNotIn("buildAppFrameSrc", workspace_source)

    def test_base_shell_remounts_app_frames_and_widgets_by_workspace(self) -> None:
        host_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/AppFrameHost.tsx").read_text()
        sidebar_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/Sidebar.tsx").read_text()
        widget_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/WidgetSlot.tsx").read_text()

        self.assertIn("mountKey: `${activeWorkspaceId}:${activeApp.app_id}`", host_source)
        self.assertIn("activeWorkspaceId={activeWorkspaceId}", sidebar_source)
        self.assertIn("activeWorkspaceId: string", widget_source)
        self.assertIn("message_id: `${activeWorkspaceId}:${hostAppId}:${contentKind}`", widget_source)
        self.assertIn("workspace_id: activeWorkspaceId", widget_source)
        self.assertIn("key={`${activeWorkspaceId}:${widget.owner_app_id}:${widget.widget_id}:${contextToken}`}", widget_source)

    def test_sidebar_uses_app_store_widget_instead_of_local_pins(self) -> None:
        sidebar_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/Sidebar.tsx").read_text()
        session_source = (REPO_ROOT / "apps/base-shell/frontend/src/session.ts").read_text()
        navigation_source = (REPO_ROOT / "apps/base-shell/frontend/src/navigation.ts").read_text()
        shortcut_source = (REPO_ROOT / "apps/app-store/frontend/dist/widgets/app-shortcuts/main.js").read_text()

        self.assertIn('contentKind="shell.sidebar.apps"', sidebar_source)
        self.assertNotIn("pinnedApps", sidebar_source)
        self.assertNotIn("pinnedAppIds", session_source)
        self.assertNotIn("nextPinnedAppIds", navigation_source)
        self.assertIn('return "New Chat"', shortcut_source)
        self.assertIn("new_chat: true", shortcut_source)

    def test_chat_sidebar_does_not_render_duplicate_new_chat_button(self) -> None:
        widget_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/main.tsx").read_text()

        self.assertNotIn('className="bs-sidebar__nav-button"', widget_source)
        self.assertNotIn('<span className="bs-sidebar__nav-title">New chat</span>', widget_source)

    def test_chat_accepts_shell_navigation_without_url_reload(self) -> None:
        chat_source = (REPO_ROOT / "apps/chat/frontend/src/App.tsx").read_text()

        self.assertIn("maverick.app.navigate", chat_source)
        self.assertIn("maverick.app.ready", chat_source)
        self.assertIn("handleNavigationParams", chat_source)
        self.assertIn("window.addEventListener(\"message\"", chat_source)
        self.assertIn("getThread(requestedThreadId)", chat_source)
        self.assertIn("activeSession || events.length > 0", chat_source)

    def test_chat_sidebar_settings_panel_escapes_scroll_clipping(self) -> None:
        widget_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/main.tsx").read_text()
        widget_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/styles.css").read_text()

        self.assertIn("window.innerHeight", widget_source)
        self.assertIn("position: fixed", widget_styles)
        self.assertIn("z-index: 1000", widget_styles)


if __name__ == "__main__":
    unittest.main()
