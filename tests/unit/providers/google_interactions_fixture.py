"""Domain fixtures extracted without changing assertions."""

from __future__ import annotations
import json
from core.providers.agentic_models import codex_routing_constraint
from core.providers.agentic_protocol import EphemeralCredential, AgenticModelRequest, AgenticRequestContentBlock, AgenticToolDefinition, AgenticToolResult

THOUGHT_SIGNATURE = "opaque-google-thought-signature"

class _ScriptedTransport:
    def __init__(
        self,
        scripts: list[list[dict[str, object] | BaseException]],
    ) -> None:
        self.scripts = scripts
        self.payloads: list[dict[str, object]] = []

    async def stream(self, *, payload, credential):
        self.payloads.append(payload)
        self.assert_credential_redacted = "test-key" not in repr(credential)
        script = self.scripts.pop(0)
        for event in script:
            if isinstance(event, BaseException):
                raise event
            yield event


def _request(
    request_id: str,
    *,
    private_state=None,
    tool_results: tuple[AgenticToolResult, ...] = (),
) -> AgenticModelRequest:
    pairing = private_state is not None and bool(tool_results)
    return AgenticModelRequest(
        schema_version="1",
        request_id=request_id,
        correlation_id="turn-google",
        model_id="gemini-3.6-flash",
        reasoning_effort="medium",
        content_blocks=(
            AgenticRequestContentBlock(
                f"{request_id}:system",
                "system",
                "public",
                "platform_instruction",
                "trusted_platform",
                "text/plain",
                b"Use synthetic fixture data only.",
            ),
            AgenticRequestContentBlock(
                f"{request_id}:user",
                "user",
                "public",
                "user_input",
                "trusted_actor",
                "text/plain",
                b"Read fixture value four.",
            ),
        ),
        tool_definitions=(
            AgenticToolDefinition(
                "fixture_read",
                "Read a synthetic fixture.",
                {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            ),
        ),
        tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=codex_routing_constraint(),
        max_output_tokens=256,
        pairing_source_journal_id=(
            f"journal:{private_state.provider_request_id}" if pairing else None
        ),
        pairing_source_turn_id=(
            private_state.turn_generation if pairing else None
        ),
        pairing_source_request_id=(
            private_state.provider_request_id if pairing else None
        ),
    )


def _tool_stream(
    interaction_id: str,
    *,
    tool_name: str = "fixture_read",
    call_id: str = "call-1",
    arguments: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    encoded_arguments = json.dumps(
        {"value": 4} if arguments is None else arguments,
        separators=(",", ":"),
    )
    return [
        _created(interaction_id),
        {"event_type": "step.start", "index": 0, "step": {"type": "thought"}},
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "thought_signature", "signature": THOUGHT_SIGNATURE},
        },
        {"event_type": "step.stop", "index": 0},
        {
            "event_type": "step.start",
            "index": 1,
            "step": {
                "type": "function_call",
                "id": call_id,
                "name": tool_name,
                "arguments": {},
            },
        },
        {
            "event_type": "step.delta",
            "index": 1,
            "delta": {"type": "arguments_delta", "arguments": encoded_arguments},
        },
        {"event_type": "step.stop", "index": 1},
        _completed(interaction_id, "requires_action", input_tokens=20, output_tokens=4),
    ]


def _text_stream(interaction_id: str, text: str) -> list[dict[str, object]]:
    return [
        _created(interaction_id),
        {"event_type": "step.start", "index": 0, "step": {"type": "model_output"}},
        {"event_type": "step.delta", "index": 0, "delta": {"type": "text", "text": text}},
        {"event_type": "step.stop", "index": 0},
        _completed(interaction_id, "completed", input_tokens=30, output_tokens=2),
    ]


def _created(interaction_id: str) -> dict[str, object]:
    return {
        "event_type": "interaction.created",
        "interaction": {"id": interaction_id, "model": "gemini-3.6-flash", "status": "in_progress"},
    }


def _completed(interaction_id: str, status: str, *, input_tokens: int, output_tokens: int):
    return {
        "event_type": "interaction.completed",
        "interaction": {
            "id": interaction_id,
            "model": "gemini-3.6-flash",
            "status": status,
            "usage": {
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
            },
        },
    }


def _public_event(event) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "text": event.text,
        "tool_call": None if event.tool_call is None else event.tool_call.arguments,
        "error_code": event.error_code,
    }


async def _events(client, request):
    return [
        event
        async for event in client.create_response(
            request,
            credential=EphemeralCredential("test-key"),
        )
    ]
