"""Tests for runtime attachment prompt materialization."""

from __future__ import annotations

import unittest

from core.runtime.attachments import input_text_with_attachment_links


class RuntimeAttachmentPromptTestCase(unittest.TestCase):
    def test_uploaded_workspace_file_links_are_appended_to_provider_input(self) -> None:
        prompt = input_text_with_attachment_links(
            input_text="Can you see this image?",
            attachments=[
                {
                    "name": "ChatGPT Image.png",
                    "type": "image/png",
                    "size": 1600000,
                    "relativePath": "storage/uploaded/file-1/ChatGPT-Image.png",
                }
            ],
            workspace_root="<repo>/workspaces/default",
        )

        self.assertIn("Can you see this image?", prompt)
        self.assertIn("Uploaded attachments:", prompt)
        self.assertIn("ChatGPT Image.png", prompt)
        self.assertIn("image/png", prompt)
        self.assertIn("storage/uploaded/file-1/ChatGPT-Image.png", prompt)
        self.assertIn("<repo>/workspaces/default/storage/uploaded/file-1/ChatGPT-Image.png", prompt)

    def test_attachment_only_turn_gets_default_provider_instruction(self) -> None:
        prompt = input_text_with_attachment_links(
            input_text="",
            attachments=[{"name": "brief.txt", "relativePath": "storage/uploaded/file-2/brief.txt"}],
            workspace_root="/workspace/acme",
        )

        self.assertTrue(prompt.startswith("Please inspect the uploaded attachment(s)."))
        self.assertIn("storage/uploaded/file-2/brief.txt", prompt)

    def test_unsafe_attachment_paths_are_not_materialized_as_local_paths(self) -> None:
        prompt = input_text_with_attachment_links(
            input_text="open this",
            attachments=[{"name": "secret", "relativePath": "../secret.txt"}],
            workspace_root="/workspace/acme",
        )

        self.assertIn("- secret", prompt)
        self.assertNotIn("../secret.txt", prompt)
        self.assertNotIn("local path:", prompt)


if __name__ == "__main__":
    unittest.main()
