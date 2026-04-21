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
        overlay_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/ShellOverlayWidgets.tsx").read_text()
        widget_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/WidgetSlot.tsx").read_text()

        self.assertIn("mountKey: `${activeWorkspaceId}:${activeApp.app_id}`", host_source)
        self.assertIn("activeWorkspaceId={activeWorkspaceId}", sidebar_source)
        self.assertIn("activeWorkspaceId={activeWorkspaceId}", overlay_source)
        self.assertIn("activeWorkspaceId: string", widget_source)
        self.assertIn("message_id: `${activeWorkspaceId}:${hostAppId}:${contentKind}`", widget_source)
        self.assertIn("workspace_id: activeWorkspaceId", widget_source)
        self.assertIn("key={`${activeWorkspaceId}:${widget.owner_app_id}:${widget.widget_id}:${contextToken}`}", widget_source)
        self.assertIn("maverick.widget.resize", widget_source)
        self.assertIn('size === "overlay"', widget_source)
        self.assertIn("activeAppId && activeAppId === widget.owner_app_id", widget_source)

    def test_base_shell_uses_registry_backed_overlay_widget(self) -> None:
        shell_source = (REPO_ROOT / "apps/base-shell/frontend/src/AppShell.tsx").read_text()
        overlay_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/ShellOverlayWidgets.tsx").read_text()

        self.assertIn("<ShellOverlayWidgets", shell_source)
        self.assertIn("activeApp={activeApp}", shell_source)
        self.assertIn("active_app", overlay_source)
        self.assertIn("activeApp.app_id", overlay_source)
        self.assertIn('hostAppId="base-shell"', overlay_source)
        self.assertIn('contentKind="shell.overlay.bottomright"', overlay_source)
        self.assertIn('size="overlay"', overlay_source)
        self.assertNotIn("chat-floating", shell_source)
        self.assertNotIn("chat-floating", overlay_source)

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
        self.assertIn("new_chat_request_id: crypto.randomUUID()", shortcut_source)

    def test_workspace_create_button_is_admin_only_in_shell(self) -> None:
        sidebar_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/Sidebar.tsx").read_text()
        switcher_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/WorkspaceSwitcher.tsx").read_text()

        self.assertIn('canCreateWorkspace={user?.platform_role === "admin"}', sidebar_source)
        self.assertIn("canCreateWorkspace: boolean", switcher_source)
        self.assertIn("canCreateWorkspace ? (", switcher_source)

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
        self.assertIn("consumeNewChatRequest", chat_source)
        self.assertIn("new_chat_request_id", chat_source)
        self.assertIn("getAgentsCommonPrompt", chat_source)
        self.assertIn("system_prompt: systemPrompt", chat_source)

    def test_empty_chat_creation_does_not_start_runtime_session(self) -> None:
        chat_source = (REPO_ROOT / "apps/chat/frontend/src/App.tsx").read_text()

        create_chat_start = chat_source.index("async function createChat(")
        create_chat_end = chat_source.index("async function handleSelectThread(", create_chat_start)
        create_chat_source = chat_source[create_chat_start:create_chat_end]

        self.assertIn('createThread("", projectId, { system_prompt: systemPrompt })', create_chat_source)
        self.assertIn("setActiveSession(null)", create_chat_source)
        self.assertNotIn("createRuntimeSession()", create_chat_source)
        self.assertIn("if (!thread.runtime_session_id)", chat_source)
        self.assertIn("system_prompt: promptWithActiveAppContext(thread.system_prompt, activeAppContext)", chat_source)
        self.assertIn("getWidgetContext", chat_source)
        self.assertIn("activeAppContextFromWidgetContext", chat_source)
        self.assertIn("mergeAppReferences(appReferencesFromText(input, mentionItems), activeAppContext)", chat_source)

    def test_chat_sidebar_settings_panel_escapes_scroll_clipping(self) -> None:
        widget_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/main.tsx").read_text()
        widget_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/styles.css").read_text()

        self.assertIn("window.innerHeight", widget_source)
        self.assertIn("position: fixed", widget_styles)
        self.assertIn("z-index: 1000", widget_styles)

    def test_chat_floating_widget_uses_chat_owned_surfaces(self) -> None:
        widget_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-floating/main.tsx").read_text()
        widget_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-floating/styles.css").read_text()

        self.assertIn('import { App } from "../../App"', widget_source)
        self.assertIn('import "../../styles/main.css"', widget_source)
        self.assertIn('import "./styles.css"', widget_source)
        self.assertIn("maverick.widget.resize", widget_source)
        self.assertIn('widget_id: "chat-floating"', widget_source)
        self.assertIn("owner_app_id: \"chat\"", widget_source)
        self.assertIn("<App enablePageCapture />", widget_source)
        self.assertIn("ChatFloatingMount", widget_source)
        self.assertIn("setIsCollapsed", widget_source)
        self.assertNotIn("if (isCollapsed) {", widget_source)
        self.assertIn('className={`chat-floating-widget-shell ${isCollapsed ? "is-hidden" : ""}`}', widget_source)
        self.assertIn('width: "3rem"', widget_source)
        self.assertIn("listThreads", widget_source)
        self.assertIn("withRuntimeAvailability", widget_source)
        self.assertIn("isThreadBusy", widget_source)
        self.assertIn("listProviders", widget_source)
        self.assertIn("selectProvider", widget_source)
        self.assertIn("getRuntimeSession", widget_source)
        self.assertIn("<ProviderSelector", widget_source)
        self.assertIn("maverick.shell.capture-area.start", (REPO_ROOT / "apps/chat/frontend/src/App.tsx").read_text())
        self.assertIn("maverick.widget.capture-area.complete", (REPO_ROOT / "apps/chat/frontend/src/App.tsx").read_text())
        self.assertIn("maverick.app.navigate", widget_source)
        self.assertIn("new_chat_request_id: crypto.randomUUID()", widget_source)
        self.assertIn('aria-label="Scegli chat"', widget_source)
        self.assertIn('aria-label="Nuova chat"', widget_source)
        self.assertIn('aria-label="Chat in lavoro"', widget_source)
        self.assertNotIn("sendRuntimeTurn", widget_source)
        self.assertNotIn("MarkdownMessage", widget_source)
        self.assertNotIn("base-shell", widget_source)
        self.assertNotIn("apps/base-shell", widget_source)
        self.assertIn(".chat-floating-widget-shell__thread-tools", widget_styles)
        self.assertIn(".chat-floating-thread-menu__trigger", widget_styles)
        self.assertIn(".chat-floating-thread-menu__item.is-busy", widget_styles)
        self.assertIn("chat-floating-working-border", widget_styles)
        self.assertIn(".chat-floating-widget-shell.is-hidden", widget_styles)
        self.assertIn(".chat-floating-widget-shell__runtime-tools", widget_styles)
        self.assertIn(".chat-floating-widget-shell__mode-icon", widget_styles)
        self.assertIn("display: none", widget_styles)
        self.assertIn("rgba(215, 36, 81, 0.18)", widget_styles)
        self.assertIn(".chat-floating-widget-shell__body .chatapp-root", widget_styles)
        self.assertIn("height: 100%", widget_styles)
        self.assertIn(".chat-floating-widget-shell__body .chatapp-chat-panel", widget_styles)
        self.assertIn(".chat-floating-widget-shell__body .chatapp-chat-workspace", widget_styles)

    def test_chat_thread_selection_stays_in_floating_wrapper(self) -> None:
        app_source = (REPO_ROOT / "apps/chat/frontend/src/App.tsx").read_text()
        header_source = (REPO_ROOT / "apps/chat/frontend/src/components/ChatHeader.tsx").read_text()
        widget_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-floating/main.tsx").read_text()

        chat_header_call = app_source[app_source.index("<ChatHeader"): app_source.index("/>", app_source.index("<ChatHeader"))]
        self.assertNotIn("activeThreadId", chat_header_call)
        self.assertNotIn("threads={threads}", chat_header_call)
        self.assertNotIn("onNewChat", chat_header_call)
        self.assertNotIn("onSelectThread", chat_header_call)
        self.assertNotIn("ChatThread", header_source)
        self.assertNotIn("chat-floating-widget-shell__title", widget_source)
        self.assertNotIn('aria-label="Scegli chat"', header_source)
        self.assertNotIn('aria-label="Nuova chat"', header_source)
        self.assertIn('aria-label="Scegli chat"', widget_source)
        self.assertIn('aria-label="Nuova chat"', widget_source)

    def test_shell_overlay_widget_supports_area_capture_without_app_dom_access(self) -> None:
        widget_slot_source = (REPO_ROOT / "apps/base-shell/frontend/src/components/WidgetSlot.tsx").read_text()
        shell_styles = (REPO_ROOT / "apps/base-shell/frontend/src/styles/layout.css").read_text()
        attachment_menu_source = (REPO_ROOT / "apps/chat/frontend/src/components/AttachmentMenu.tsx").read_text()

        self.assertIn("maverick.shell.capture-area.start", widget_slot_source)
        self.assertIn("navigator.mediaDevices.getDisplayMedia", widget_slot_source)
        self.assertIn("maverick.widget.capture-area.complete", widget_slot_source)
        self.assertIn("new File([blob]", widget_slot_source)
        self.assertIn("bs-capture-overlay", shell_styles)
        self.assertIn("Cattura area pagina", attachment_menu_source)
        self.assertNotIn("contentDocument", widget_slot_source)
        self.assertNotIn("contentWindow.document", widget_slot_source)


if __name__ == "__main__":
    unittest.main()
