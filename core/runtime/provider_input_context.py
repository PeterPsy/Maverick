"""Transient governed context composition for runtime provider input."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from core.egress.classification import CanonicalSourceClassification
from core.runtime.app_references import input_text_with_app_references
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
    input_text: str,
    app_references: list[dict[str, object]] | None,
    attachments: list[dict[str, object]] | None,
) -> tuple[RuntimeProviderInputSource, ...]:
    """Keep prompt, orchestration, attachment, and app provenance separate."""
    sources: list[RuntimeProviderInputSource] = [
        RuntimeProviderInputSource(
            source_id="turn-prompt",
            provenance="user_input",
            content_type="text/plain",
            content=input_text,
        )
    ]
    orchestration = _generalist_orchestration_source(state, session=session)
    if orchestration is not None:
        sources.append(
            RuntimeProviderInputSource(
                source_id="generalist-orchestration",
                provenance="governed_context",
                content_type="application/json",
                content=orchestration,
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
    for index, attachment in enumerate(attachments or ()):
        if not isinstance(attachment, dict):
            continue
        sources.append(
            RuntimeProviderInputSource(
                source_id=f"attachment:{index}",
                provenance="attachment",
                content_type="text/plain",
                content=input_text_with_attachment_links(
                    input_text="",
                    attachments=[dict(attachment)],
                    workspace_root=session.workspace_root,
                ),
                classification=_attachment_classification(
                    filesystem,
                    attachment=attachment,
                ),
                capability_modality=str(
                    attachment.get("type")
                    or attachment.get("content_type")
                    or ""
                ).strip().lower()
                or None,
            )
        )
    if filesystem is not None:
        filesystem.close()
    return tuple(sources)


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
