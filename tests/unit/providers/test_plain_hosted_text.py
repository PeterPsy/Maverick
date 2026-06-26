from __future__ import annotations

from datetime import UTC, datetime
import unittest

from core.providers.models import ProviderModelOption
from core.providers.text_generation import HostedTextGenerationError
from core.runtime.plain_hosted_text import _hosted_message_content
from core.runtime.runtime_session import RuntimeSessionRecord
from tests.support.repo import make_temp_repo_root


class PlainHostedTextAttachmentTest(unittest.TestCase):
    def session(self, workspace_root: str) -> RuntimeSessionRecord:
        now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
        return RuntimeSessionRecord(
            session_id="sess-hosted",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode=None,
            effective_mode="sandbox",
            workspace_root=workspace_root,
            workdir=workspace_root,
            runtime_root=f"{workspace_root}/runtime/sessions/sess-hosted",
            started_at=now,
            updated_at=now,
            ended_at=None,
            last_progress_at=now,
            runtime_mode="plain_hosted_chat",
        )

    def model(self, input_modalities: list[str]) -> ProviderModelOption:
        return ProviderModelOption(
            model_id="audio-model",
            label="Audio model",
            description=None,
            default_reasoning_effort=None,
            input_modalities=input_modalities,
            output_modalities=["text"],
        )

    def test_materializes_supported_audio_attachment_as_inline_data(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = "storage/uploaded/chat/recording.wav"
        path = repo_root / "workspaces" / "default" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

        content = _hosted_message_content(
            input_text="Transcribe this.",
            attachments=[
                {
                    "name": "recording.wav",
                    "type": "audio/wav",
                    "relativePath": relative_path,
                }
            ],
            session=self.session(str(repo_root / "workspaces" / "default")),
            model_option=self.model(["text", "audio"]),
            provider_id="openrouter",
        )

        self.assertIsInstance(content, list)
        self.assertEqual(content[1].type, "inline_data")
        self.assertEqual(content[1].mime_type, "audio/wav")
        self.assertEqual(content[1].data, "YXVkaW8=")
        self.assertEqual(content[1].filename, "recording.wav")

    def test_rejects_attachments_not_declared_by_model(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = "storage/uploaded/chat/recording.wav"
        path = repo_root / "workspaces" / "default" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

        with self.assertRaises(HostedTextGenerationError) as raised:
            _hosted_message_content(
                input_text="Transcribe this.",
                attachments=[
                    {
                        "name": "recording.wav",
                        "type": "audio/wav",
                        "relativePath": relative_path,
                    }
                ],
                session=self.session(str(repo_root / "workspaces" / "default")),
                model_option=self.model(["text"]),
                provider_id="openrouter",
            )

        self.assertEqual(raised.exception.reason_code, "plain_hosted_chat_model_blocks_attachments")


if __name__ == "__main__":
    unittest.main()
