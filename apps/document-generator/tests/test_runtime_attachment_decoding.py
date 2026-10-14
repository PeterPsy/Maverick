"""RuntimeAttachmentDecodingTests fixtures extracted without changing assertions."""

from __future__ import annotations
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from core.apps.contracts import parse_app_contract_file
from core.runtime.research_attachments import research_input_text
from tests.support.research_attachment_fixture import ResearchAttachmentFixture


class RuntimeAttachmentDecodingTests(ResearchAttachmentFixture, unittest.TestCase):
    def test_document_bytes_are_decoded_by_the_declared_app_backend(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="urn:w"><w:p><w:t>Document evidence</w:t></w:p></w:document>')
        attachment = self.attachment("source.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        app_root = self.state.repository_root / "apps/document-generator"
        parsed = parse_app_contract_file(app_root)
        binding = SimpleNamespace(app_id="document-generator", data_root=str(self.harness.root / "data"))
        self.state.app_store = SimpleNamespace()
        with patch("core.apps.runtime_attachment_text.enabled_workspace_app_bindings", return_value=[binding]), patch(
            "core.apps.runtime_attachment_text.resolve_workspace_app_surface", return_value=(app_root, parsed),
        ):
            sources = self.sources([attachment], text="")
        self.assertEqual(sources[0].content["text"], "Document evidence")
        self.assertIn("Document evidence", research_input_text("", sources))
