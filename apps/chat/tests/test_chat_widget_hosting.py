from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class ChatWidgetHostingTests(unittest.TestCase):
    def test_chat_declares_runtime_text_widget_without_fleet_host(self) -> None:
        contract_source = (REPO_ROOT / "apps/chat/app_contract.json").read_text()
        vite_source = (REPO_ROOT / "apps/chat/vite.config.ts").read_text()
        widget_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/runtime-text/main.tsx").read_text()
        widget_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/runtime-text/styles.css").read_text()

        self.assertIn('"widget_id": "chat-runtime-text"', contract_source)
        self.assertIn('"host": "chat"', contract_source)
        self.assertNotIn('"host": "fleet"', contract_source)
        self.assertIn('"chat.runtime.text.preview"', contract_source)
        self.assertIn('"widgets/runtime-text/index": "frontend/widgets/runtime-text/index.html"', vite_source)
        self.assertIn("useRuntimeEvents", widget_source)
        self.assertIn("getWidgetContext", widget_source)
        self.assertIn("eventsToMessages(events)", widget_source)
        self.assertNotIn("latestRuntimeStepLabel", widget_source)
        self.assertNotIn("Working", widget_source)
        self.assertNotIn("agent_label", widget_source)
        self.assertNotIn("chat-runtime-text__agent", widget_source)
        self.assertNotIn("chat-runtime-text__status", widget_source)
        self.assertNotIn("sendRuntimeTurn", widget_source)
        self.assertNotIn("createRuntimeSession", widget_source)
        self.assertNotIn("fetch(", widget_source)
        self.assertIn("overflow: hidden;", widget_styles)
        self.assertIn("overflow-y: auto;", widget_styles)
        self.assertNotIn("chat-runtime-text__agent", widget_styles)
        self.assertNotIn("chat-runtime-text__status", widget_styles)

    def test_chat_declares_separate_shell_sidebar_primary_and_footer_widgets(self) -> None:
        contract_source = (REPO_ROOT / "apps/chat/app_contract.json").read_text()
        vite_source = (REPO_ROOT / "apps/chat/vite.config.ts").read_text()
        sidebar_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/main.tsx").read_text()
        footer_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar-footer/main.tsx").read_text()

        self.assertIn('"widget_id": "chat-sidebar"', contract_source)
        self.assertIn('"shell.sidebar.primary"', contract_source)
        self.assertIn('"widget_id": "chat-sidebar-footer"', contract_source)
        self.assertIn('"shell.sidebar.footer"', contract_source)
        self.assertIn('"widgets/chat-sidebar-footer/index": "frontend/widgets/chat-sidebar-footer/index.html"', vite_source)
        self.assertNotIn("bs-chat-sidebar-footer", sidebar_source)
        self.assertNotIn("New chat</span>", sidebar_source)
        self.assertIn("bs-chat-sidebar-footer__new-chat", footer_source)
        self.assertIn('const PRIMARY_ACTION_LABEL = "New chat";', footer_source)
        self.assertIn("<span>{primaryActionLabel}</span>", footer_source)
        self.assertIn("maverick.widget.open-app", footer_source)
        self.assertIn("new_chat_request_id", footer_source)

        footer_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar-footer/styles.css").read_text()
        self.assertIn("backdrop-filter: blur(18px) saturate(1.15);", footer_styles)

    def test_chat_declares_shell_right_dock_widget(self) -> None:
        contract_source = (REPO_ROOT / "apps/chat/app_contract.json").read_text()
        vite_source = (REPO_ROOT / "apps/chat/vite.config.ts").read_text()
        dock_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-floating-dock/main.tsx").read_text()
        frame_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-floating/FloatingChatFrame.tsx").read_text()

        self.assertIn('"widget_id": "chat-floating-dock"', contract_source)
        self.assertIn('"shell.dock.right"', contract_source)
        self.assertIn('"shell.overlay.mobile.fullscreen"', contract_source)
        self.assertIn('"mount": "frontend/dist/widgets/chat-floating-dock"', contract_source)
        self.assertIn('"widgets/chat-floating-dock/index": "frontend/widgets/chat-floating-dock/index.html"', vite_source)
        self.assertIn("ChatFloatingDockMount", dock_source)
        self.assertIn("FloatingChatFrame", dock_source)
        self.assertIn("mobile-fullscreen", dock_source)
        self.assertIn('showClose={dock.mode !== "mobile-fullscreen"}', dock_source)
        self.assertIn("showOverlay", dock_source)
        self.assertIn("postDockClose", dock_source)
        self.assertIn('aria-label="Dock chat to right"', frame_source)
        self.assertIn('aria-label="Return chat to overlay"', frame_source)

    def test_chat_sidebar_project_button_creates_without_opening_settings_panel(self) -> None:
        sidebar_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/main.tsx").read_text()
        project_actions_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/useSidebarProjectActions.ts").read_text()
        project_section_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/ProjectSection.tsx").read_text()
        sidebar_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/styles.css").read_text()

        self.assertIn('const payload = await createProject("New project");', project_actions_source)
        self.assertIn("updateFromSidebarPayload(payload, setProjects);", project_actions_source)
        self.assertIn("onClick={() => void onAddProject()}", project_section_source)
        self.assertNotIn("addProject(panelPositionFromTrigger", project_actions_source)
        self.assertNotIn("setPanel(position ? { kind: \"project\", project: payload.project, position } : null);", project_actions_source)
        self.assertNotIn("SettingsPanel", sidebar_source + project_section_source)
        self.assertNotIn("bs-sidebar-floating-panel", sidebar_styles)

    def test_chat_sidebar_project_actions_are_inline(self) -> None:
        sidebar_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/main.tsx").read_text()
        project_state_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/useChatSidebarState.ts").read_text()
        project_actions_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/useSidebarProjectActions.ts").read_text()
        project_section_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/ProjectSection.tsx").read_text()
        project_delete_source = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/ProjectDeleteConfirm.tsx").read_text()
        sidebar_styles = (REPO_ROOT / "apps/chat/frontend/src/widgets/chat-sidebar/styles.css").read_text()

        self.assertIn("const [editingProject, setEditingProject]", project_actions_source)
        self.assertIn("cancelProjectEditFromOutside", project_actions_source)
        self.assertIn("onStartProjectEdit(project);", project_section_source)
        self.assertIn('{isEditingProject ? "check" : "more_horiz"}', project_section_source)
        self.assertIn('{isEditingProject ? "delete" : "add"}', project_section_source)
        self.assertIn("bs-chat-folder__title-input", project_section_source)
        self.assertIn("bs-chat-project-delete-confirm", project_delete_source)
        self.assertIn(".bs-chat-folder.is-project-editing .bs-folder-menu__trigger", sidebar_styles)
        self.assertIn(".bs-chat-project-delete-confirm", sidebar_styles)
        self.assertNotIn("window.confirm", sidebar_source + project_state_source + project_actions_source + project_section_source)
        self.assertNotIn("panelPositionFromTrigger", sidebar_source + project_state_source + project_actions_source + project_section_source)

    def test_chat_structured_messages_use_generic_widget_host(self) -> None:
        structured_source = (REPO_ROOT / "apps/chat/frontend/src/components/StructuredContentMessage.tsx").read_text()
        host_source = (REPO_ROOT / "apps/chat/frontend/src/components/WidgetHostFrame.tsx").read_text()
        launch_source = (REPO_ROOT / "apps/chat/frontend/src/lib/nestedWidgetFrame.ts").read_text()
        structured_styles = (REPO_ROOT / "apps/chat/frontend/src/styles/chat/transcript/structured-content.css").read_text()

        self.assertIn("<WidgetHostFrame", structured_source)
        self.assertIn('hostAppId="chat"', structured_source)
        self.assertIn("<MorphingSpinner", structured_source)
        self.assertIn('aria-live="polite"', structured_source)
        self.assertIn("Caricamento widget…", structured_source)
        self.assertNotIn("Ricerca widget compatibile", structured_source)
        self.assertIn(".chatapp-structured-widget-loader", structured_styles)
        self.assertIn("listWidgets(hostAppId, content.kind)", host_source)
        self.assertIn("createWidgetContext", host_source)
        self.assertIn("host_app_id: hostAppId", host_source)
        self.assertIn("owner_app_id: widget.owner_app_id", host_source)
        self.assertIn("widget_id: widget.widget_id", host_source)
        self.assertIn("message_id: messageId", host_source)
        self.assertIn("content,", host_source)
        self.assertIn("requestNestedWidgetLaunch(widget, context.context_token)", host_source)
        self.assertIn('src="about:blank"', host_source)
        self.assertIn("submitNestedWidgetBootstrap(frame, state.launch)", host_source)
        self.assertIn('"/api/apps/widgets/browser-launch"', launch_source)
        self.assertIn("record.parent_origin !== normalizedParentOrigin", launch_source)
        self.assertIn("record.owner_app_id !== widget.owner_app_id", launch_source)
        self.assertIn("event.origin !== launch.origin", launch_source)
        self.assertIn("event.source !== frame?.contentWindow", launch_source)
        self.assertIn("sandbox={MAVERICK_WIDGET_IFRAME_SANDBOX}", host_source)
        self.assertNotIn("widgetContextTokenFromLocation", host_source)

    def test_chat_widget_host_leaves_visual_chrome_to_widget_owner(self) -> None:
        structured_styles = (REPO_ROOT / "apps/chat/frontend/src/styles/chat/transcript/structured-content.css").read_text()
        widget_styles = re.findall(r"\.chatapp-structured-widget\s*\{(?P<body>[^}]*)\}", structured_styles)

        self.assertTrue(widget_styles)
        for styles in widget_styles:
            self.assertIn("border: 0;", styles)
            self.assertIn("background: transparent;", styles)

    def test_chat_widget_host_bounds_resize_messages(self) -> None:
        host_source = (REPO_ROOT / "apps/chat/frontend/src/components/WidgetHostFrame.tsx").read_text()
        resize_source = (REPO_ROOT / "apps/chat/frontend/src/lib/widgetResize.ts").read_text()

        self.assertIn("boundedWidgetHeightPx(payload.height)", host_source)
        self.assertIn("payload.owner_app_id === widget.owner_app_id", host_source)
        self.assertIn("payload.widget_id === widget.widget_id", host_source)
        self.assertIn("STRUCTURED_WIDGET_MIN_HEIGHT_PX", resize_source)
        self.assertIn("STRUCTURED_WIDGET_MAX_HEIGHT_PX", resize_source)

    def test_chat_transcript_triggers_widget_previews_from_workspace_file_links(self) -> None:
        transcript_source = (REPO_ROOT / "apps/chat/frontend/src/lib/transcript.ts").read_text()
        preview_source = (REPO_ROOT / "apps/chat/frontend/src/lib/linkPreviews.ts").read_text()

        self.assertRegex(transcript_source, r"structuredContentFromAgentLinks\((text|finalText)\)")
        self.assertIn('kind: "workspace.file.preview"', preview_source)
        self.assertIn("workspace_relative_path", preview_source)
        self.assertIn("generated|uploaded", preview_source)

    def test_chat_widget_host_has_no_widget_owner_imports(self) -> None:
        host_source = (REPO_ROOT / "apps/chat/frontend/src/components/WidgetHostFrame.tsx").read_text()

        self.assertNotIn("gallery", host_source.lower())
        self.assertNotIn("checklist", host_source.lower())
        self.assertNotIn("../../", host_source)
        self.assertNotIn("/apps/", host_source)
        self.assertNotIn("apps/", host_source)

    def test_chat_widget_host_keeps_iframe_stable_across_transcript_rerenders(self) -> None:
        host_source = (REPO_ROOT / "apps/chat/frontend/src/components/WidgetHostFrame.tsx").read_text()

        self.assertIn("key={`${hostAppId}:${messageId}:${state.widget.owner_app_id}:${state.widget.widget_id}:${state.contextToken}`}", host_source)
        self.assertIn("stableContentSignature(content)", host_source)
        self.assertIn("[contentSignature, hostAppId, messageId]", host_source)
        self.assertNotIn("[content, hostAppId, messageId]", host_source)
        self.assertIn("if (!cancelled)", host_source)


if __name__ == "__main__":
    unittest.main()
