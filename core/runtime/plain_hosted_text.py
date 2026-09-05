"""Plain hosted text runtime bridge for non-agentic chat sessions."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
from typing import Callable

from core.observability.service import record_platform_event
from core.providers.errors import ProviderError
from core.providers.models import ProviderDefinition, ProviderModelOption, RoutingDecision
from core.providers.hosted_text_profiles import (
    hosted_text_provider_routing_snapshot,
    validate_hosted_text_execution_binding,
)
from core.providers.payloads import routing_decision_payload
from core.providers.routing import ProviderRoutingContext, primary_routing_failure_reason, select_provider_for_profile
from core.providers.service import effective_provider_registry
from core.providers.text_generation import (
    FakeHostedTextTransport,
    HostedTextGenerationError,
    TextGenerationContentPart,
    TextGenerationMessage,
    TextGenerationRequest,
    TextGenerationUsage,
    execute_hosted_text_generation,
)
from core.runtime.execution import RuntimeExecutionResult
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.plain_hosted_cancellation import plain_hosted_request_cancellation
from core.runtime.plain_hosted_history import build_plain_hosted_message_history
from core.runtime.runtime_session import RuntimeSessionRecord


HOSTED_TEXT_RUNTIME_PROVIDER_ID = "hosted-text-runtime"
MAX_PLAIN_HOSTED_ATTACHMENTS = 8
MAX_PLAIN_HOSTED_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_PLAIN_HOSTED_ATTACHMENTS_TOTAL_BYTES = MAX_PLAIN_HOSTED_ATTACHMENT_BYTES
DEFAULT_HOSTED_TEXT_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class _AttachmentSource:
    attachment: dict[str, object]
    path: Path
    mime_type: str
    size_bytes: int


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
    invoked_skill_ids: list[str] | None = None,
) -> None:
    """Fail closed on agentic/operative features before prompt materialization."""
    if not runtime_session_is_plain_hosted_chat(session):
        return
    if session.skill_ids or invoked_skill_ids:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_skills")
    if app_references:
        raise HostedTextGenerationError("plain_hosted_chat_blocks_app_references")
    attachment_limit_error = plain_hosted_chat_attachment_limit_error(attachments)
    if attachment_limit_error is not None:
        raise HostedTextGenerationError(attachment_limit_error)


def plain_hosted_chat_attachment_limit_error(attachments: list[dict[str, object]] | None) -> str | None:
    """Return a stable error when plain-hosted attachment metadata exceeds cheap submit-time limits."""
    if len(_attachment_items(attachments)) > MAX_PLAIN_HOSTED_ATTACHMENTS:
        return "plain_hosted_chat_too_many_attachments"
    return None


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
    text_binding = session.hosted_text_binding
    if text_binding is not None:
        try:
            validate_hosted_text_execution_binding(text_binding)
        except ValueError as error:
            raise HostedTextGenerationError("hosted_text_binding_invalid") from error
    registry = effective_provider_registry(
        state.provider_store,
        registry=getattr(state, "provider_registry", None),
    )
    decision = select_provider_for_profile(
        "plain_hosted_chat",
        ProviderRoutingContext(
            workspace_id=session.workspace_id,
            provider_store=state.provider_store,
            registry=registry,
            secret_store=state.secret_store,
            request_id=None,
            hosted_provider_id=(
                text_binding.provider_id
                if text_binding is not None
                else session.hosted_provider_id
            ),
            hosted_model_id=(
                text_binding.model_id
                if text_binding is not None
                else session.hosted_model_id
            ),
        ),
    )
    _emit_routing_decision_event(event_sink, decision)
    _record_platform_routing_decision(state, session=session, decision=decision)
    if decision.execution_path != "plain_hosted_text" or decision.selected_provider_id is None:
        reason = primary_routing_failure_reason(decision)
        raise HostedTextGenerationError(reason, reason_codes=decision.reason_codes)
    if text_binding is not None and (
        decision.selected_provider_id != text_binding.provider_id
        or decision.selected_model_id_or_voice_id != text_binding.model_id
    ):
        raise HostedTextGenerationError(
            "hosted_text_session_route_changed",
            reason_codes=[*decision.reason_codes, "hosted_text_session_route_changed"],
        )
    definition = registry.get_provider_definition(decision.selected_provider_id)
    model_option = _selected_model_option(
        definition,
        decision.selected_model_id_or_voice_id,
    )
    if model_option is None:
        raise HostedTextGenerationError("hosted_text_model_unavailable")
    if text_binding is not None:
        live_routing = hosted_text_provider_routing_snapshot(
            state.provider_store,
            workspace_id=session.workspace_id,
            provider_id=decision.selected_provider_id,
            model_id=decision.selected_model_id_or_voice_id or "",
        )
        try:
            validate_hosted_text_execution_binding(
                text_binding,
                definition=definition,
                model=model_option,
                provider_routing_snapshot=live_routing,
            )
        except ProviderError as error:
            reason_code = str(error).strip() or "hosted_text_profile_unavailable"
            raise HostedTextGenerationError(reason_code) from error
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
        max_output_tokens=_max_output_tokens(session),
        stream=True,
        timeout_seconds=30,
        workspace_id=session.workspace_id,
        workspace_root=session.workspace_root,
        provider_routing=(
            text_binding.provider_routing_snapshot
            if text_binding is not None
            else _openrouter_provider_routing_for_decision(
                state,
                session=session,
                decision=decision,
            )
        ),
    )
    try:
        with plain_hosted_request_cancellation(
            session_id=session.session_id,
            turn_id=turn_id,
            store=state.runtime_store,
        ) as cancellation:
            result = execute_hosted_text_generation(
                state.provider_store,
                state.secret_store,
                decision=decision,
                request=request,
                runtime_session_id=session.session_id,
                endpoint_url=(
                    text_binding.profile.endpoint_id
                    if text_binding is not None
                    else None
                ),
                transport=_fake_transport_from_environment(),
                delta_sink=_hosted_delta_sink(event_sink, decision=decision),
                sent_sink=_hosted_provider_sent_sink(on_provider_turn_start_sent, decision=decision),
                accepted_sink=_hosted_provider_accepted_sink(on_provider_accepted, decision=decision),
                cancellation=cancellation,
            )
    except HostedTextGenerationError as error:
        raise HostedTextGenerationError(
            error.reason_code,
            reason_codes=[*decision.reason_codes, error.reason_code],
        ) from error
    _emit_plain_hosted_usage(
        event_sink,
        session=session,
        turn_id=turn_id,
        decision=decision,
        model_option=model_option,
        usage=result.usage,
        provider_routing=request.provider_routing,
    )
    return RuntimeExecutionResult(output_text=result.output_text, exit_code=0), decision


def _emit_plain_hosted_usage(
    event_sink: Callable[[RuntimeExecutionEvent], object] | None,
    *,
    session: RuntimeSessionRecord,
    turn_id: str | None,
    decision: RoutingDecision,
    model_option: ProviderModelOption | None,
    usage: TextGenerationUsage | None,
    provider_routing: dict[str, object] | None,
) -> None:
    if event_sink is None or usage is None:
        return
    event_sink(
        RuntimeExecutionEvent(
            event_type="provider.usage",
            payload={
                "usage_id": f"plain-hosted:{session.session_id}:{turn_id or 'turn'}",
                "provider_id": decision.selected_provider_id or "",
                "model_id": decision.selected_model_id_or_voice_id or "",
                "source": "plain_hosted_chat",
                "semantics": "incremental",
                "token_accuracy": "exact",
                "context_accuracy": "estimated",
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "cache_write_input_tokens": usage.cache_write_input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_output_tokens": usage.reasoning_output_tokens,
                "total_tokens": usage.total_tokens,
                "context_tokens": usage.total_tokens,
                "context_window_tokens": _plain_hosted_context_window(model_option, provider_routing),
            },
        )
    )


def _plain_hosted_context_window(
    model_option: ProviderModelOption | None,
    provider_routing: dict[str, object] | None,
) -> int | None:
    if model_option is None:
        return None
    metadata_value = model_option.metadata.get("context_length")
    if isinstance(metadata_value, int) and not isinstance(metadata_value, bool) and metadata_value > 0:
        return metadata_value
    selected_upstream = str((provider_routing or {}).get("provider_id") or "").strip()
    candidates = [
        int(option["context_length"])
        for option in model_option.upstream_provider_options
        if isinstance(option.get("context_length"), int)
        and not isinstance(option.get("context_length"), bool)
        and int(option["context_length"]) > 0
        and (not selected_upstream or option.get("provider_id") == selected_upstream)
    ]
    if not candidates and selected_upstream:
        return _plain_hosted_context_window(model_option, None)
    return min(candidates) if candidates else None


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
                "acceptance_slo_scope": "hosted_http_provider",
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
                "acceptance_slo_scope": "hosted_http_provider",
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
    if session.hosted_text_binding is not None:
        return dict(session.hosted_text_binding.provider_routing_snapshot) or None
    get_selection = getattr(state.provider_store, "get_hosted_provider_selection", None)
    if not callable(get_selection):
        return None
    selection = get_selection(workspace_id=session.workspace_id, profile="fast_model")
    if selection is None:
        return None
    routing = selection.openrouter_provider_routing_by_model.get(decision.selected_model_id_or_voice_id)
    return dict(routing) if isinstance(routing, dict) else None


def _max_output_tokens(session: RuntimeSessionRecord) -> int:
    binding = session.hosted_text_binding
    limit = None if binding is None else binding.profile.output_limit_tokens
    if limit is None:
        return DEFAULT_HOSTED_TEXT_MAX_OUTPUT_TOKENS
    return min(DEFAULT_HOSTED_TEXT_MAX_OUTPUT_TOKENS, limit)


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
    attachment_items = _attachment_items(attachments)
    if not attachment_items:
        return input_text
    input_modalities = set(model_option.input_modalities if model_option is not None else [])
    sources = _attachment_sources(
        attachments=attachment_items,
        input_modalities=input_modalities,
        provider_id=provider_id,
        workspace_root=session.workspace_root,
    )
    parts = [TextGenerationContentPart(type="text", text=input_text.strip() or "Please inspect the uploaded attachment(s).")]
    total_read_bytes = 0
    for source in sources:
        raw = _read_bounded_attachment_bytes(source.path)
        total_read_bytes += len(raw)
        if total_read_bytes > MAX_PLAIN_HOSTED_ATTACHMENTS_TOTAL_BYTES:
            raise HostedTextGenerationError("plain_hosted_chat_attachments_too_large")
        parts.append(_attachment_content_part(source=source, raw=raw))
    return parts


def _attachment_items(attachments: list[dict[str, object]] | None) -> list[dict[str, object]]:
    return [item for item in attachments or [] if isinstance(item, dict)]


def _attachment_sources(
    *,
    attachments: list[dict[str, object]],
    input_modalities: set[str],
    provider_id: str,
    workspace_root: str,
) -> list[_AttachmentSource]:
    if len(attachments) > MAX_PLAIN_HOSTED_ATTACHMENTS:
        raise HostedTextGenerationError("plain_hosted_chat_too_many_attachments")
    sources: list[_AttachmentSource] = []
    total_size_bytes = 0
    for attachment in attachments:
        source = _attachment_source(
            attachment=attachment,
            input_modalities=input_modalities,
            provider_id=provider_id,
            workspace_root=workspace_root,
        )
        total_size_bytes += source.size_bytes
        if total_size_bytes > MAX_PLAIN_HOSTED_ATTACHMENTS_TOTAL_BYTES:
            raise HostedTextGenerationError("plain_hosted_chat_attachments_too_large")
        sources.append(source)
    return sources


def _attachment_source(
    *,
    attachment: dict[str, object],
    input_modalities: set[str],
    provider_id: str,
    workspace_root: str,
) -> _AttachmentSource:
    content_type = _string_value(attachment.get("type") or attachment.get("content_type"))
    if not _attachment_modality_supported(content_type=content_type, input_modalities=input_modalities, provider_id=provider_id):
        raise HostedTextGenerationError("plain_hosted_chat_model_blocks_attachments")
    relative_path = _safe_workspace_relative_path(_string_value(attachment.get("relativePath") or attachment.get("relative_path")))
    if not relative_path:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable")
    path = _local_attachment_path(workspace_root=workspace_root, relative_path=relative_path)
    if not path.is_file():
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable")
    size_bytes = _bounded_attachment_size(path)
    mime_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return _AttachmentSource(attachment=attachment, path=path, mime_type=mime_type, size_bytes=size_bytes)


def _attachment_content_part(*, source: _AttachmentSource, raw: bytes) -> TextGenerationContentPart:
    encoded = base64.b64encode(raw).decode("ascii")
    if source.mime_type.startswith("image/"):
        return TextGenerationContentPart(type="image_url", image_url=f"data:{source.mime_type};base64,{encoded}")
    return TextGenerationContentPart(
        type="inline_data",
        mime_type=source.mime_type,
        data=encoded,
        filename=_string_value(source.attachment.get("name") or source.attachment.get("filename")) or source.path.name,
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


def _read_bounded_attachment_bytes(path: Path) -> bytes:
    _bounded_attachment_size(path)
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_PLAIN_HOSTED_ATTACHMENT_BYTES + 1)
    except OSError as error:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable") from error
    if len(raw) > MAX_PLAIN_HOSTED_ATTACHMENT_BYTES:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_too_large")
    return raw


def _bounded_attachment_size(path: Path) -> int:
    try:
        size_bytes = path.stat().st_size
    except OSError as error:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_unavailable") from error
    if size_bytes > MAX_PLAIN_HOSTED_ATTACHMENT_BYTES:
        raise HostedTextGenerationError("plain_hosted_chat_attachment_too_large")
    return size_bytes


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
