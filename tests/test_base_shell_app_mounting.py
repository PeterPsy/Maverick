from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class BaseShellAppMountingTests(unittest.TestCase):
    def test_base_shell_uses_persistent_app_frames(self) -> None:
        host_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/AppFrameHost.tsx").read_text()
        workspace_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/WorkspaceView.tsx").read_text()

        self.assertIn("maverick.app.navigate", host_source)
        self.assertIn("postMessage", host_source)
        self.assertIn("src={app.frontend_mount}", host_source)
        self.assertNotIn("URLSearchParams", workspace_source)
        self.assertNotIn("buildAppFrameSrc", workspace_source)

    def test_chat_accepts_shell_navigation_without_url_reload(self) -> None:
        chat_source = (REPO_ROOT / "apps/chat/frontend/src/App.tsx").read_text()

        self.assertIn("maverick.app.navigate", chat_source)
        self.assertIn("handleNavigationParams", chat_source)
        self.assertIn("window.addEventListener(\"message\"", chat_source)
        self.assertIn("getThread(requestedThreadId)", chat_source)


if __name__ == "__main__":
    unittest.main()
