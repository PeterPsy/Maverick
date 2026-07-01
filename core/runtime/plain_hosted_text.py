"""Plain hosted text runtime bridge for non-agentic chat sessions."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
from typing import Callable

from core.observability.service import record_platform_event
from core.providers.models import ProviderDefinition, ProviderModelOption, RoutingDecision
from core.providers.payloads import routing_decision_payload
from core.providers.routing import ProviderRoutingContext, primary_routing_failure_reason, select_provider_for_profile
from core.providers.service import effective_provider_registry
from core.providers.text_generation import (
    FakeHostedTextTransport,
    HostedTextGenerationError,
    TextGenerationContentPart,
    TextGenerationMessage,
    TextGenerationRequest,
    execute_hosted_text_generation,
)
from core.runtime.execution import RuntimeExecutionResult
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.plain_hosted_history import build_plain_hosted_message_history
from core.runtime.runtime_session import RuntimeSessionRecord


HOSTED_TEXT_RUNTIME_PROVIDER_ID = "hosted-text-runtime"
DEFAULT_HOSTED_TEXT_MAX_OUTPUT_TOKENS = 4096


def runtime_session_is_plain_hosted_chat(session: RuntimeSessionRecord) -> bool:
    """Return whether a session should use the plain hosted text bridge."""
    return getattr(session, "runtime_mode", "agentic") == "plain_hosted_chat"


def queue_provider_id_for_session(session: RuntimeSessionRecord) -> str:
    """Return the provider id used before a concrete hosted provider is routed."""
    if runtime_session_is_plain_hosted_chat(session):
        return HOSTED_TEXT_RUNTIME_PROVIDER_ID
    return str(session.provider_id or "codex")


def assert_plain_hosted_chat_input_allowed(
    session: RuntimeSessionRecord,
    *,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
) -> None:
    """Fail closed on agentic/operative features before prompt materialization."""
    if not runtime_session_is_plain_hosted_chat(session):
        return
    if session.skill_ids:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_skills")
    if app_references:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_app_references")


def execute_plain_hosted_text_turn(
    state,
    *,
    session: RuntimeSessionRecord,
    turn_id: str | None = None,
    input_text: str,
    attachments: list[dict[str, object]] | None = None,
    event_sink: Callable[[RuntimeExecutionEvent], object] | None = None,
    on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
    on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
) -> tuple[RuntimeExecutionResult, RoutingDecision]:
    """Execute one plain hosted chat turn through a routed hosted text provider."""
    decision = select_provider_for_profile(
        "fast_model",
        ProviderRoutingContext(
            workspace_id=session.workspace_id,
            provider_store=state.provider_store,
            registry=effective_provider_registry(state.provider_store),
            secret_store=state.secret_store,
            request_id=None,
            hosted_provider_id=session.hosted_provider_id,
            hosted_model_id=session.hosted_model_id,
        ),
    )
    _emit_routing_decision_event(event_sink, decision)
    _record_platform_routing_decision(state, session=session, decision=decision)
    if decision.execution_path != "plain_hosted_text" or decision.selected_provider_id is None:
        reason = primary_routing_failure_reason(decision)
        raise HostedTextGenerationError(reason, reason_codes=decision.reason_codes)
    model_option = _selected_model_option(
        effective_provider_registry(state.provider_store).get_provider_definition(decision.selected_provider_id),
        decision.selected_model_id_or_voice_id,
    )
    messages = build_plain_hosted_message_history(
        state.runtime_store,
        session_id=session.session_id,
        current_turn_id=turn_id,
        current_input_text=input_text,
    )
    messages[-1] = TextGenerationMessage(
        role="user",
        content=_hosted_message_content(
            input_text=input_text,
            attachments=attachments,
            session=session,
            model_option=model_option,
            provider_id=decision.selected_provider_id or "",
        ),
    )
    request = TextGenerationRequest(
        model_id=decision.selected_model_id_or_voice_id or "",
        system_prompt=session.system_prompt,
        messages=messages,
        max_output_tokens=DEFAULT_HOSTED_TEXT_MAX_OUTPUT_TOKENS,
        stream=True,
        timeout_seconds=30,
        workspace_id=session.workspace_id,
        workspace_root=session.workspace_root,
        provider_routing=_openrouter_provider_routing_for_decision(state, session=session, decision=decision),
    )
    try:
        result = execute_hosted_text_generation(
            state.provider_store,
            state.secret_store,
            decision=decision,
            request=request,
            runtime_session_id=session.session_id,
            transport=_fake_transport_from_environment(),
            delta_sink=_hosted_delta_sink(event_sink, decision=decision),
            sent_sink=_hosted_provider_sent_sink(on_provider_turn_start_sent, decision=decision),
            accepted_sink=_hosted_provider_accepted_sink(on_provider_accepted, decision=decision),
        )
    except HostedTextGenerationError as error:
        raise HostedTextGenerationError(
            error.reason_code,
            reason_codes=[*decision.reason_codes, error.reason_code],
        ) from error
    return RuntimeExecutionResult(output_text=result.output_text, exit_code=0), decision


def _hosted_provider_sent_sink(
    on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None,
    *,
    decision: RoutingDecision,
) -> Callable[[dict[str, object]], None] | None:
    if on_provider_turn_start_sent is None:
        return None

    def sink(metadata: dict[str, object]) -> None:
        on_provider_turn_start_sent(
            {
                **metadata,
                "provider_id": decision.selected_provider_id or "",
                "model_id": decision.selected_model_id_or_voice_id or "",
            }
        )

    return sink


def _hosted_provider_accepted_sink(
    on_provider_accepted: Callable[[dict[str, object]], None] | None,
    *,
    decision: RoutingDecision,
) -> Callable[[dict[str, object]], None] | None:
    if on_provider_accepted is None:
        return None

    def sink(metadata: dict[str, object]) -> None:
        on_provider_accepted(
            {
                **metadata,
                "provider_id": decision.selected_provider_id or "",
                "model_id": decision.selected_model_id_or_voice_id or "",
            }
        )

    return sink


def _openrouter_provider_routing_for_decision(
    state,
    *,
    session: RuntimeSessionRecord,
    decision: RoutingDecision,
) -> dict[str, object] | None:
    if decision.selected_provider_id != "openrouter" or not decision.selected_model_id_or_voice_id:
        return None
    get_selection = getattr(state.provider_store, "get_hosted_provider_selection", None)
    if not callable(get_selection):
        return None
    selection = get_selection(workspace_id=session.workspace_id, profile="fast_model")
    if selection is None:
        return None
    routing = selection.openrouter_provider_routing_by_model.get(decision.selected_model_id_or_voice_id)
    return dict(routing) if isinstance(routing, dict) else None


def _selected_model_option(definition: ProviderDefinition, model_id: str | None) -> ProviderModelOption | None:
    if not model_id:
        return None
    return next((option for option in definition.model_options if option.model_id == model_id), None)


def _hosted_message_content(
    *,
    input_text: str,
    attachments: list[dict[str, object]] | None,
    session: RuntimeSessionRecord,
    model_option: ProviderModelOption | None,
    provider_id: str = "",
) -> str | list[TextGenerationContentPart]:
    attachment_items = [item for item in attachments or [] if isinstance(item, dict)]
    if not attachment_items:
        return input_text
    input_modalities = set(model_option.input_modalities if model_option is not None else [])
    parts = [TextGenerationContentPart(type="text", text=input_text.strip() or "Please inspect the uploaded attachment(s).")]
    for attachment in attachment_items:
        parts.append(
            _attachment_content_part(
                attachment=attachment,
                input_modalities=input_modalities,
                provider_id=provider_id,
                workspace_root=session.workspace_root,
            )
        )
    return parts


def _attachment_content_part(
    *,
    attachment: dict[str, object],
    input_modalities: set[str],
    provider_id: str,
    workspace_root: str,
) -> TextGenerationContentPart:
    content_type = _string_value(attachment.get("type") or attachment.get("content_type"))
    if not _attachment_modality_supported(content_type=content_type, input_modalities=input_modalities, provider_id=provider_id):
        raise HostedTextGenerationError("plain_hosted_chat_model_blocks_attachments")
    relative_path = _safe_workspace_relative_path(_string_value(attachment.get("relativePath") or attachment.get("relative_path")))
    if not relative_path:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable")
    path = _local_attachment_path(workspace_root=workspace_root, relative_path=relative_path)
    if not path.is_file():
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable")
    raw = path.read_bytes()
    mime_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(raw).decode("ascii")
    if mime_type.startswith("image/"):
        return TextGenerationContentPart(type="image_url", image_url=f"data:{mime_type};base64,{encoded}")
    return TextGenerationContentPart(
        type="inline_data",
        mime_type=mime_type,
        data=encoded,
        filename=_string_value(attachment.get("name") or attachment.get("filename")) or path.name,
    )


def _attachment_modality_supported(*, content_type: str, input_modalities: set[str], provider_id: str) -> bool:
    normalized_type = content_type.lower()
    modality = _attachment_modality(normalized_type)
    if modality == "text":
        return "text" in input_modalities or "file" in input_modalities or "document" in input_modalities
    if modality == "pdf":
        return provider_id == "openrouter" or bool({"pdf", "file", "document"} & input_modalities)
    if modality == "document":
        return bool({"document", "file"} & input_modalities)
    if modality == "spreadsheet":
        return bool({"spreadsheet", "document", "file"} & input_modalities)
    return modality in input_modalities or "file" in input_modalities


def _attachment_modality(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("text/") or content_type == "application/json":
        return "text"
    if content_type == "application/pdf":
        return "pdf"
    if content_type in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return "document"
    if content_type in {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        return "spreadsheet"
    return "file"


def _safe_workspace_relative_path(value: str) -> str:
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return ""
    if len(path.parts) < 3 or path.parts[0] != "storage" or path.parts[1] not in {"uploaded", "generated"}:
        return ""
    return path.as_posix()


def _local_attachment_path(*, workspace_root: str, relative_path: str) -> Path:
    root = Path(workspace_root).resolve()
    candidate = (root / PurePosixPath(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable") from error
    return candidate


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _emit_routing_decision_event(
    event_sink: Callable[[RuntimeExecutionEvent], object] | None,
    decision: RoutingDecision,
) -> None:
    if event_sink is None:
        return
    event_sink(
        RuntimeExecutionEvent(
            event_type="provider.routing.decision",
            payload=routing_decision_payload(decision),
        )
    )


def _hosted_delta_sink(
    event_sink: Callable[[RuntimeExecutionEvent], object] | None,
    *,
    decision: RoutingDecision,
) -> Callable[[str], None] | None:
    if event_sink is None:
        return None

    def emit_delta(delta: str) -> None:
        if not delta:
            return
        event_sink(
            RuntimeExecutionEvent(
                event_type="runtime.output.delta",
                payload={
                    "text": delta,
                    "provider_id": decision.selected_provider_id,
                    "model_id": decision.selected_model_id_or_voice_id,
                    "runtime_mode": "plain_hosted_chat",
                },
            )
        )

    return emit_delta


def _record_platform_routing_decision(state, *, session: RuntimeSessionRecord, decision: RoutingDecision) -> None:
    observability_store = getattr(state, "observability_store", None)
    if observability_store is None:
        return
    record_platform_event(
        observability_store,
        event_type="provider.routing.decision",
        event_plane="runtime",
        source_domain="providers",
        workspace_id=session.workspace_id,
        runtime_session_id=session.session_id,
        provider_id=decision.selected_provider_id,
        payload=routing_decision_payload(decision),
    )


def _fake_transport_from_environment() -> FakeHostedTextTransport | None:
    response = os.environ.get("MAVERICK_HOSTED_TEXT_FAKE_RESPONSE")
    chunks = os.environ.get("MAVERICK_HOSTED_TEXT_FAKE_CHUNKS")
    if response is None and chunks is None:
        return None
    parsed_chunks = _json_string_list(chunks)
    if response is not None and not parsed_chunks:
        parsed_chunks = [response]
    return FakeHostedTextTransport(
        response_text=response or "".join(parsed_chunks) or "fake hosted response",
        chunks=parsed_chunks,
    )


def _json_string_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item)]
    return [str(parsed)]
