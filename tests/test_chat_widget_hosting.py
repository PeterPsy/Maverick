from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class ChatWidgetHostingTests(unittest.TestCase):
    def test_chat_structured_messages_use_generic_widget_host(self) -> None:
        structured_source = (REPO_ROOT / "apps/chat/frontend/src/components/StructuredContentMessage.tsx").read_text()
        host_source = (REPO_ROOT / "apps/chat/frontend/src/components/WidgetHostFrame.tsx").read_text()

        self.assertIn("<WidgetHostFrame", structured_source)
        self.assertIn('hostAppId="chat"', structured_source)
        self.assertIn("listWidgets(hostAppId, content.kind)", host_source)
        self.assertIn("createWidgetContext", host_source)
        self.assertIn("host_app_id: hostAppId", host_source)
        self.assertIn("owner_app_id: widget.owner_app_id", host_source)
        self.assertIn("widget_id: widget.widget_id", host_source)
        self.assertIn("message_id: messageId", host_source)
        self.assertIn("content,", host_source)
        self.assertIn("state.widget.frontend_mount", host_source)
        self.assertIn("context=", host_source)

    def test_chat_transcript_triggers_widget_previews_from_workspace_file_links(self) -> None:
        transcript_source = (REPO_ROOT / "apps/chat/frontend/src/lib/transcript.ts").read_text()
        preview_source = (REPO_ROOT / "apps/chat/frontend/src/lib/linkPreviews.ts").read_text()

        self.assertIn("structuredContentFromAgentLinks(text)", transcript_source)
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
