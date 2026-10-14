from __future__ import annotations

import base64
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_adapter import RuntimeTurnContext
from core.providers.codex_app_server_device_use_turn import codex_turn_input
from core.providers.errors import AgenticRuntimeError
from core.providers.google_interactions_request import google_interaction_payload
from core.providers.google_interactions_state import initial_google_interaction_state
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import (
    decode_openrouter_chat_state, encode_openrouter_chat_state, initial_openrouter_chat_state,
)
from core.runtime.message_steering import attempt_runtime_message_steer
from core.runtime.research_attachments import research_input_text, validate_research_attachments
from core.runtime.semantic_envelope import HostedSemanticEnvelopeCompiler
from tests.unit.providers.google_interactions_fixture import _request as google_request
from tests.unit.providers.test_openrouter_agentic_codec import _request as openrouter_request
from tests.unit.runtime_state import test_research_runtime
from tests.support.research_attachment_fixture import ResearchAttachmentFixture


class ResearchAttachmentsTest(ResearchAttachmentFixture, unittest.TestCase):


    def test_text_and_image_snapshots_reach_native_and_hosted_inputs_without_paths(self):
        image = b"exact image fixture"
        sources = self.sources([
            self.attachment("notes.txt", b"User selected evidence.", "text/plain"),
            self.attachment("scan.png", image, "image/png"),
        ])
        self.assertEqual([source.provenance for source in sources], ["user_input", "attachment", "attachment"])
        for source in sources[1:]:
            self.assertEqual(source.projection_mode, "inline")
            self.assertIsNone(source.attachment_read_fence)
            self.assertNotIn("workspace_relative_path", source.content)
            self.assertIsNotNone(source.classification)
        text = research_input_text("Analyze these.", sources)
        self.assertIn("User selected evidence.", text)
        self.assertNotIn("storage/", text)
        _, research, turn_input = codex_turn_input(
            self.session, SimpleNamespace(), text, (), input_sources=sources,
        )
        self.assertTrue(research)
        self.assertEqual(turn_input[1], {"type": "image", "url": "data:image/png;base64," + base64.b64encode(image).decode()})
        context = RuntimeTurnContext(
            session=self.session, binding=self.harness.binding,
            provider_state=self.harness.provider_state, input_text=text,
            correlation_id="turn-hosted", effective_authority=self.harness.authority,
            input_sources=sources,
        )
        envelope = HostedSemanticEnvelopeCompiler(
            classifier=self.harness.classify, platform_instruction="hidden platform",
        ).compile(
            context=context, input_text=text, catalog=test_research_runtime.ResearchRuntimeTest.research_catalog(),
            tool_results=(), provider_private_state=None, request_phase="exploration",
        )
        self.assertEqual([block.provenance for block in envelope.blocks if block.kind == "content"],
                         ["platform_instruction", "user_input", "attachment", "attachment"])
        self.assertNotIn("hidden platform", str(envelope))

    def test_paths_symlinks_missing_files_and_actual_byte_limits_are_rejected(self):
        for relative in ("../secret", "/etc/passwd", "data/chat/private.txt", "storage/uploaded/../private.txt"):
            with self.subTest(relative=relative), self.assertRaises(AgenticRuntimeError):
                validate_research_attachments([{"relativePath": relative}])
        attachment = self.attachment("notes.txt", b"too large", "text/plain")
        attachment["size"] = 1
        with patch("core.runtime.research_attachments.MAX_RESEARCH_ATTACHMENT_BYTES", 2):
            with self.assertRaisesRegex(AgenticRuntimeError, "research_attachment_limit_exceeded"):
                self.sources([attachment])
        target = Path(self.session.workspace_root) / attachment["relativePath"]
        target.unlink()
        target.symlink_to(self.harness.root / "AGENTS.md")
        with self.assertRaisesRegex(AgenticRuntimeError, "research_attachment_unavailable"):
            self.sources([attachment])
        with self.assertRaisesRegex(AgenticRuntimeError, "research_attachment_limit_exceeded"):
            validate_research_attachments([attachment] * 9)


    def test_research_attachments_queue_instead_of_using_text_only_steering(self):
        with patch("core.runtime.message_steering._persisted_message_attempt", return_value=None):
            attempt = attempt_runtime_message_steer(
                self.state, session=self.session, input_text="Follow up",
                client_message_id="attachment-follow-up",
                attachments=[self.attachment("scan.png", b"image", "image/png")],
            )
        self.assertEqual(attempt.status, "fallback")
        self.assertEqual(attempt.reason, "research_attachments_require_new_turn")

    def test_inline_images_render_on_hosted_wires_and_survive_openrouter_history(self):
        source = self.sources([self.attachment("scan.png", b"image", "image/png")])[1]
        encoded = json.dumps(source.content).encode()
        for request_factory, payload_factory, state in (
            (google_request, google_interaction_payload, initial_google_interaction_state("stateless")),
            (openrouter_request, openrouter_chat_payload, initial_openrouter_chat_state()),
        ):
            request = request_factory("attachment-request")
            block = replace(request.content_blocks[-1], provenance="attachment", content_type="application/json", content=encoded)
            request = replace(request, content_blocks=(*request.content_blocks, block))
            payload, history = payload_factory(request, state)
            self.assertIn(base64.b64encode(b"image").decode(), json.dumps(payload))
            if request_factory is openrouter_request:
                updated = replace(state, history=history)
                self.assertEqual(decode_openrouter_chat_state(encode_openrouter_chat_state(updated)).history, history)
