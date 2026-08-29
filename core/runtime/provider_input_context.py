"""Transient governed context composition for runtime provider input."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
)
from core.runtime.app_references import input_text_with_app_references
from core.runtime.attachment_projection import attachment_read_encoding
from core.runtime.attachments import input_text_with_attachment_links
from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.workspaces.data_governance import resource_classification_for_observation


@dataclass(frozen=True)
class RuntimeProviderInputSource:
    """One provenance-preserving source presented to an agentic request builder."""

    source_id: str
    provenance: str
    content_type: str
    content: object
    role: str = "user"
    classification: CanonicalSourceClassification | None = None
    capability_modality: str | None = None
    projection_mode: str | None = None


@dataclass(frozen=True)
class RuntimeProviderInputObservation:
    """Server-owned identity for one transient turn input at admission."""

    workspace_id: str
    session_id: str
    turn_id: str
    source_id: str
    provenance: str
    content_type: str
    source_ref: str
    source_revision: str
    source_digest: str
    resource_identity: str


RuntimeProviderInputClassificationResolver = Callable[
    [RuntimeProviderInputObservation, object], CanonicalSourceClassification
]


def generalist_orchestration_input_text(state: Any, *, session: Any, input_text: str) -> str:
    """Attach root orchestration context without persisting it in the turn."""
    # Lazy import avoids the inter-agent service -> runtime submission cycle.
    from core.inter_agent.generalist_context import input_text_with_generalist_orchestration_context

    return input_text_with_generalist_orchestration_context(state, session=session, input_text=input_text)


def runtime_provider_input_text(
    state: Any,
    *,
    session: Any,
    input_text: str,
    app_references: list[dict[str, object]] | None,
    attachments: list[dict[str, object]] | None,
) -> str:
    """Build agentic provider input from governed context and materialized references."""
    governed_input = generalist_orchestration_input_text(state, session=session, input_text=input_text)
    return input_text_with_attachment_links(
        input_text=input_text_with_app_references(input_text=governed_input, app_references=app_references),
        attachments=attachments,
        workspace_root=session.workspace_root,
    )


def runtime_provider_input_sources(
    state: Any,
    *,
    session: Any,
    turn_id: str,
    input_text: str,
    app_references: list[dict[str, object]] | None,
    attachments: list[dict[str, object]] | None,
) -> tuple[RuntimeProviderInputSource, ...]:
    """Keep prompt, orchestration, attachment, and app provenance separate."""
    sources: list[RuntimeProviderInputSource] = []
    agent_instruction = str(getattr(session, "system_prompt", "") or "")
    if agent_instruction:
        sources.append(
            RuntimeProviderInputSource(
                source_id="agent-instruction",
                provenance="agent_instruction",
                content_type="text/plain",
                content=agent_instruction,
                role="developer",
                classification=_transient_input_classification(
                    state,
                    session=session,
                    turn_id=turn_id,
                    source_id="agent-instruction",
                    provenance="agent_instruction",
                    content_type="text/plain",
                    content=agent_instruction,
                ),
            )
        )
    sources.append(
        RuntimeProviderInputSource(
            source_id="turn-prompt",
            provenance="user_input",
            content_type="text/plain",
            content=input_text,
            classification=_transient_input_classification(
                state,
                session=session,
                turn_id=turn_id,
                source_id="turn-prompt",
                provenance="user_input",
                content_type="text/plain",
                content=input_text,
            ),
        )
    )
    orchestration = _generalist_orchestration_source(state, session=session)
    if orchestration is not None:
        sources.append(
            RuntimeProviderInputSource(
                source_id="generalist-orchestration",
                provenance="governed_context",
                content_type="application/json",
                content=orchestration,
                classification=_transient_input_classification(
                    state,
                    session=session,
                    turn_id=turn_id,
                    source_id="generalist-orchestration",
                    provenance="governed_context",
                    content_type="application/json",
                    content=orchestration,
                ),
            )
        )
    for index, reference in enumerate(app_references or ()):
        if isinstance(reference, dict):
            sources.append(
                RuntimeProviderInputSource(
                    source_id=f"app-reference:{index}",
                    provenance="app_reference",
                    content_type="text/plain",
                    content=input_text_with_app_references(
                        input_text="",
                        app_references=[dict(reference)],
                    ).strip(),
                    classification=_app_reference_classification(
                        state,
                        session=session,
                        reference=reference,
                    ),
                )
            )
    filesystem = _attachment_filesystem(state, session=session)
    try:
        for index, attachment in enumerate(attachments or ()):
            sources.append(
                _attachment_input_source(
                    filesystem,
                    index=index,
                    attachment=attachment,
                )
            )
    finally:
        if filesystem is not None:
            filesystem.close()
    return tuple(sources)


def _transient_input_classification(
    state: Any,
    *,
    session: Any,
    turn_id: str,
    source_id: str,
    provenance: str,
    content_type: str,
    content: object,
) -> CanonicalSourceClassification:
    """Resolve a transient source only through the trusted admission hook."""
    try:
        encoded = canonical_egress_content(content)
    except (TypeError, ValueError):
        encoded = b""
    source_digest = hashlib.sha256(encoded).hexdigest() if encoded else ""
    workspace_id = str(getattr(session, "workspace_id", "") or "")
    session_id = str(getattr(session, "session_id", "") or "")
    normalized_turn_id = str(turn_id or "").strip()
    source_ref = f"runtime-turn:{normalized_turn_id}:{source_id}"
    identity = (
        f"runtime-input:{workspace_id}:{session_id}:{normalized_turn_id}:"
        f"{source_id}:{source_digest}"
    )
    fallback = fail_closed_classification(
        provenance=provenance,
        source_ref=source_ref,
        source_revision=source_digest,
        source_digest=source_digest,
        resource_identity=identity,
    )
    resolver = getattr(state, "runtime_input_classification_resolver", None)
    if (
        not callable(resolver)
        or not workspace_id
        or not session_id
        or not normalized_turn_id
        or not source_digest
    ):
        return fallback
    observation = RuntimeProviderInputObservation(
        workspace_id=workspace_id,
        session_id=session_id,
        turn_id=normalized_turn_id,
        source_id=source_id,
        provenance=provenance,
        content_type=content_type,
        source_ref=source_ref,
        source_revision=source_digest,
        source_digest=source_digest,
        resource_identity=identity,
    )
    try:
        candidate = resolver(observation, content)
        normalized = join_classifications((candidate,)).sources[0]
    except Exception:
        return fallback
    if (
        normalized.provenance != provenance
        or normalized.source_ref != source_ref
        or normalized.source_revision != source_digest
        or normalized.source_digest != source_digest
        or normalized.resource_identity != identity
    ):
        return fallback
    return normalized


def _attachment_input_source(
    filesystem: ConfinedWorkspaceFilesystem | None,
    *,
    index: int,
    attachment: object,
) -> RuntimeProviderInputSource:
    if not isinstance(attachment, dict):
        raise ValueError("agentic_attachment_metadata_invalid")
    for field_name in ("id", "name"):
        if field_name in attachment and not isinstance(
            attachment[field_name],
            str,
        ):
            raise ValueError("agentic_attachment_metadata_invalid")
    relative_path = _validated_attachment_relative_path(
        attachment.get("relativePath") or attachment.get("relative_path")
    )
    raw_media_type = (
        attachment.get("type")
        or attachment.get("content_type")
        or "application/octet-stream"
    )
    if not isinstance(raw_media_type, str) or not raw_media_type.strip():
        raise ValueError("agentic_attachment_metadata_invalid")
    media_type = raw_media_type.strip().lower()
    size_bytes = (
        attachment.get("size")
        if "size" in attachment
        else attachment.get("size_bytes")
    )
    if size_bytes is not None and (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 0
    ):
        raise ValueError("agentic_attachment_metadata_invalid")
    return RuntimeProviderInputSource(
        source_id=f"attachment:{index}",
        provenance="attachment",
        content_type="application/json",
        content={
            "attachment_id": str(attachment.get("id") or ""),
            "name": str(attachment.get("name") or ""),
            "workspace_relative_path": relative_path,
            "media_type": media_type,
            "size_bytes": size_bytes,
            "projection": {
                "mode": "workspace_reference",
                "read_capability": "core-capability:filesystem.read",
                "read_encoding": attachment_read_encoding(media_type),
            },
        },
        classification=_attachment_classification(
            filesystem,
            attachment=attachment,
        ),
        capability_modality=media_type,
        projection_mode="workspace_reference",
    )


def _validated_attachment_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("agentic_attachment_metadata_invalid")
    relative_path = value.strip()
    path = PurePosixPath(relative_path)
    if (
        not relative_path
        or "\\" in relative_path
        or "\x00" in relative_path
        or path.is_absolute()
        or path.as_posix() != relative_path
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("agentic_attachment_metadata_invalid")
    return relative_path


def _generalist_orchestration_source(state: Any, *, session: Any) -> dict[str, object] | None:
    store = getattr(state, "inter_agent_store", None)
    if store is None:
        return None
    from core.inter_agent.generalist_context import generalist_orchestration_context

    value = generalist_orchestration_context(
        store,
        workspace_id=session.workspace_id,
        root_runtime_session_id=session.session_id,
    )
    if value is None:
        return None
    # Round-trip through bounded JSON to ensure no custom object reaches a codec.
    return json.loads(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    )


def _attachment_filesystem(
    state: Any,
    *,
    session: Any,
) -> ConfinedWorkspaceFilesystem | None:
    workspace_store = getattr(state, "workspace_store", None)
    get_classification = getattr(workspace_store, "get_resource_classification", None)
    if not callable(get_classification):
        return None

    def resolve(observation, provenance: str) -> CanonicalSourceClassification:
        return resource_classification_for_observation(
            get_classification(
                workspace_id=observation.workspace_id,
                resource_kind=observation.resource_kind,
                resource_ref=observation.resource_ref,
            ),
            workspace_id=observation.workspace_id,
            resource_kind=observation.resource_kind,
            resource_ref=observation.resource_ref,
            resource_identity=observation.resource_identity,
            resource_revision=observation.resource_revision,
            resource_digest=observation.resource_digest,
            provenance=provenance,
        )

    try:
        return ConfinedWorkspaceFilesystem(
            workspace_id=session.workspace_id,
            workspace_root=Path(session.workspace_root),
            classification_resolver=resolve,
        )
    except Exception:
        return None


def _attachment_classification(
    filesystem: ConfinedWorkspaceFilesystem | None,
    *,
    attachment: dict[str, object],
) -> CanonicalSourceClassification | None:
    if filesystem is None:
        return None
    relative_path = str(
        attachment.get("relativePath")
        or attachment.get("relative_path")
        or ""
    ).strip()
    if not relative_path:
        return None
    try:
        _observation, classification = filesystem.observe_file(
            relative_path,
            provenance="attachment",
        )
        return classification
    except Exception:
        return None


def _app_reference_classification(
    state: Any,
    *,
    session: Any,
    reference: dict[str, object],
) -> CanonicalSourceClassification | None:
    resolver = getattr(state, "runtime_app_reference_classification_resolver", None)
    if not callable(resolver):
        return None
    try:
        result = resolver(
            workspace_id=session.workspace_id,
            reference=dict(reference),
            provenance="app_reference",
        )
    except Exception:
        return None
    return result if isinstance(result, CanonicalSourceClassification) else None
