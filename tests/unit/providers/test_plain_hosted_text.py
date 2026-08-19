from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.models import ProviderModelOption, RoutingDecision
from core.providers.text_generation import HostedTextGenerationError
from core.runtime.plain_hosted_text import (
    _hosted_message_content,
    _hosted_provider_accepted_sink,
    _hosted_provider_sent_sink,
    assert_plain_hosted_chat_input_allowed,
)
from core.runtime.turn_submission_service_output import _record_provider_accepted, _record_provider_turn_start_sent
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

    def routing_decision(self) -> RoutingDecision:
        return RoutingDecision(
            request_id="request-1",
            workspace_id="default",
            profile="fast_model",
            requested_capabilities=["text"],
            candidate_provider_ids=["openrouter"],
            selected_provider_id="openrouter",
            selected_model_id_or_voice_id="audio-model",
            selected_runtime_engine_id=None,
            execution_path="plain_hosted_text",
            policy_id_or_version="test",
            credential_authorization_required=True,
            provider_credential_binding_id_optional=None,
            app_secret_grant_id_optional=None,
            fallback_used=False,
            reason_codes=[],
            created_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
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

    def test_provider_lifecycle_sinks_mark_hosted_http_slo_scope(self) -> None:
        sent_payloads: list[dict[str, object]] = []
        accepted_payloads: list[dict[str, object]] = []

        sent_sink = _hosted_provider_sent_sink(sent_payloads.append, decision=self.routing_decision())
        accepted_sink = _hosted_provider_accepted_sink(accepted_payloads.append, decision=self.routing_decision())
        assert sent_sink is not None
        assert accepted_sink is not None

        sent_sink({"source": "fake"})
        accepted_sink({"status_code": 200})

        self.assertEqual(sent_payloads[0]["acceptance_slo_scope"], "hosted_http_provider")
        self.assertEqual(accepted_payloads[0]["acceptance_slo_scope"], "hosted_http_provider")
        self.assertEqual(accepted_payloads[0]["provider_id"], "openrouter")

    def test_provider_lifecycle_events_preserve_hosted_http_slo_scope(self) -> None:
        class StubRuntimeStore:
            def get_session(self, session_id: str):
                return SimpleNamespace(workspace_id="default")

            def save_event(self, event):
                return event

        state = SimpleNamespace(runtime_store=StubRuntimeStore(), runtime_event_bus=None)

        sent = _record_provider_turn_start_sent(
            state,
            session_id="sess-hosted",
            turn_id="turn-hosted",
            provider_id="openrouter",
            runtime_mode="plain_hosted_chat",
            metadata={"acceptance_slo_scope": "hosted_http_provider"},
        )
        accepted = _record_provider_accepted(
            state,
            session_id="sess-hosted",
            turn_id="turn-hosted",
            provider_id="openrouter",
            runtime_mode="plain_hosted_chat",
            elapsed_ms=25,
            metadata={
                "acceptance_slo_scope": "hosted_http_provider",
                "request_id": "request-1",
                "provider_response_id": "generation-1",
                "upstream_id": "deepinfra/fp8",
            },
        )

        self.assertEqual(sent.payload["acceptance_slo_scope"], "hosted_http_provider")
        self.assertEqual(accepted.payload["acceptance_slo_scope"], "hosted_http_provider")
        self.assertEqual(accepted.payload["turn_start_to_ack_ms"], 25)
        self.assertEqual(accepted.payload["request_id"], "request-1")
        self.assertEqual(accepted.payload["provider_response_id"], "generation-1")
        self.assertEqual(accepted.payload["upstream_id"], "deepinfra/fp8")

    def test_rejects_oversized_attachment_before_reading_bytes(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = "storage/uploaded/chat/recording.wav"
        path = repo_root / "workspaces" / "default" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

        with patch("core.runtime.plain_hosted_text.MAX_PLAIN_HOSTED_ATTACHMENT_BYTES", 4), patch(
            "pathlib.Path.read_bytes",
            side_effect=AssertionError("read_bytes must not be used for hosted attachments"),
        ), self.assertRaises(HostedTextGenerationError) as raised:
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
                model_option=self.model(["text", "audio"]),
                provider_id="openrouter",
            )

        self.assertEqual(raised.exception.reason_code, "plain_hosted_chat_attachment_too_large")

    def test_rejects_too_many_attachments_before_stat(self) -> None:
        attachments = [
            {
                "name": f"recording-{index}.wav",
                "type": "audio/wav",
                "relativePath": f"storage/uploaded/chat/recording-{index}.wav",
            }
            for index in range(9)
        ]

        with patch("pathlib.Path.stat", side_effect=AssertionError("attachment paths must not be statted")), self.assertRaises(HostedTextGenerationError) as raised:
            _hosted_message_content(
                input_text="Transcribe these.",
                attachments=attachments,
                session=self.session("/tmp/workspace"),
                model_option=self.model(["text", "audio"]),
                provider_id="openrouter",
            )

        self.assertEqual(raised.exception.reason_code, "plain_hosted_chat_too_many_attachments")

    def test_plain_hosted_input_guard_rejects_too_many_attachments_before_queue(self) -> None:
        attachments = [
            {
                "name": f"recording-{index}.wav",
                "type": "audio/wav",
                "relativePath": f"storage/uploaded/chat/recording-{index}.wav",
            }
            for index in range(9)
        ]

        with self.assertRaises(HostedTextGenerationError) as raised:
            assert_plain_hosted_chat_input_allowed(
                self.session("/tmp/workspace"),
                attachments=attachments,
                app_references=[],
            )

        self.assertEqual(raised.exception.reason_code, "plain_hosted_chat_too_many_attachments")

    def test_rejects_aggregate_attachment_bytes_before_opening_files(self) -> None:
        repo_root = make_temp_repo_root(self)
        relative_path = "storage/uploaded/chat/recording.wav"
        path = repo_root / "workspaces" / "default" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"abc")

        attachment = {
            "name": "recording.wav",
            "type": "audio/wav",
            "relativePath": relative_path,
        }
        with patch("core.runtime.plain_hosted_text.MAX_PLAIN_HOSTED_ATTACHMENTS_TOTAL_BYTES", 5), patch(
            "pathlib.Path.open",
            side_effect=AssertionError("aggregate over-limit attachments must not be opened"),
        ), self.assertRaises(HostedTextGenerationError) as raised:
            _hosted_message_content(
                input_text="Transcribe these.",
                attachments=[attachment, attachment],
                session=self.session(str(repo_root / "workspaces" / "default")),
                model_option=self.model(["text", "audio"]),
                provider_id="openrouter",
            )

        self.assertEqual(raised.exception.reason_code, "plain_hosted_chat_attachments_too_large")

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
