"""Core-owned classification for transient provider input admitted by a turn."""

from __future__ import annotations

import hashlib
import re

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
    join_trust_levels,
    validated_classification,
)
from core.runtime.provider_input_context import (
    RuntimeProviderInputClassificationResolver,
    RuntimeProviderInputObservation,
)
from core.workspaces.data_governance import (
    resource_classification_for_observation,
)


RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION = 2
RUNTIME_PROVIDER_INPUT_RESOURCE_KIND = "runtime_input"
GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND = "inter_agent_governed_context"
_INDEXED_SOURCE = re.compile(r"^(app-reference|attachment):(\d+):metadata$")
_FIXED_SOURCES = {
    "agent-instruction": ("agent_instruction", "text/plain"),
    "turn-prompt": ("user_input", "text/plain"),
    "generalist-orchestration": ("governed_context", "application/json"),
}
_INDEXED_PROVENANCE = {
    "app-reference": ("app_reference", "text/plain"),
    "attachment": ("attachment", "application/json"),
}


def build_runtime_provider_input_classification_resolver(
    *,
    workspace_store,
) -> RuntimeProviderInputClassificationResolver:
    """Resolve exact transient resources through workspace classification."""

    def resolve(observation, content):
        return classify_admitted_runtime_provider_input(
            observation,
            content,
            workspace_store=workspace_store,
        )

    return resolve


def classify_admitted_runtime_provider_input(
    observation: RuntimeProviderInputObservation,
    content: object,
    *,
    workspace_store=None,
) -> CanonicalSourceClassification:
    """Classify only exact transient sources materialized by Core for this turn.

    This is deliberately not a generic provenance fallback.  The accepted
    source ids and content types are the closed provider-input composition
    contract, and the classification is bound to the exact canonical bytes and
    workspace/session/turn identity supplied by that composition.
    """
    fallback = fail_closed_classification(
        provenance=str(getattr(observation, "provenance", "") or "tool_result"),
        source_ref=str(getattr(observation, "source_ref", "") or ""),
        source_revision=str(getattr(observation, "source_revision", "") or ""),
        source_digest=str(getattr(observation, "source_digest", "") or ""),
        resource_identity=str(
            getattr(observation, "resource_identity", "") or ""
        ),
    )
    if not isinstance(observation, RuntimeProviderInputObservation):
        return fallback
    if any(
        not isinstance(getattr(observation, field_name), str)
        for field_name in (
            "workspace_id",
            "session_id",
            "turn_id",
            "source_id",
            "provenance",
            "content_type",
            "source_ref",
            "source_revision",
            "source_digest",
            "resource_identity",
        )
    ):
        return fallback
    expected_source = _expected_source_contract(observation.source_id)
    if expected_source is None:
        return fallback
    expected_provenance, expected_content_type = expected_source
    if (
        observation.provenance != expected_provenance
        or observation.content_type != expected_content_type
        or not observation.workspace_id
        or not observation.session_id
        or not observation.turn_id
    ):
        return fallback
    try:
        digest = hashlib.sha256(canonical_egress_content(content)).hexdigest()
    except (TypeError, ValueError):
        return fallback
    source_ref = f"runtime-turn:{observation.turn_id}:{observation.source_id}"
    identity = (
        f"runtime-input:{observation.workspace_id}:{observation.session_id}:"
        f"{observation.turn_id}:{observation.source_id}:{digest}"
    )
    if (
        observation.source_ref != source_ref
        or observation.source_revision != digest
        or observation.source_digest.lower() != digest
        or observation.resource_identity != identity
    ):
        return fallback
    if observation.source_id == "generalist-orchestration":
        return _classify_generalist_orchestration(
            observation,
            content,
            workspace_store=workspace_store,
            fallback=fallback,
        )
    get_classification = getattr(
        workspace_store,
        "get_resource_classification",
        None,
    )
    if not callable(get_classification):
        return fallback
    try:
        record = get_classification(
            workspace_id=observation.workspace_id,
            resource_kind=RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
            resource_ref=source_ref,
        )
    except Exception:
        return fallback
    return resource_classification_for_observation(
        record,
        workspace_id=observation.workspace_id,
        resource_kind=RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
        resource_ref=source_ref,
        resource_identity=identity,
        resource_revision=digest,
        resource_digest=digest,
        provenance=observation.provenance,
    )


def _classify_generalist_orchestration(
    observation: RuntimeProviderInputObservation,
    content: object,
    *,
    workspace_store,
    fallback: CanonicalSourceClassification,
) -> CanonicalSourceClassification:
    """Join exact persisted context sources; never classify the aggregate by id."""
    chunks = _generalist_context_source_chunks(content)
    get_classification = getattr(
        workspace_store,
        "get_resource_classification",
        None,
    )
    if chunks is None or not callable(get_classification):
        return fallback
    sources: list[CanonicalSourceClassification] = []
    for resource_ref, chunk in chunks:
        try:
            digest = hashlib.sha256(canonical_egress_content(chunk)).hexdigest()
            identity = (
                f"governed-context-source:{observation.workspace_id}:"
                f"{resource_ref}:{digest}"
            )
            record = get_classification(
                workspace_id=observation.workspace_id,
                resource_kind=GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
                resource_ref=resource_ref,
            )
        except Exception:
            return fallback
        sources.append(
            resource_classification_for_observation(
                record,
                workspace_id=observation.workspace_id,
                resource_kind=GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
                resource_ref=resource_ref,
                resource_identity=identity,
                resource_revision=digest,
                resource_digest=digest,
                provenance="governed_context",
            )
        )
    joined = join_classifications(sources)
    proof_complete = bool(sources) and all(
        source.classification_revision is not None for source in sources
    )
    return validated_classification(
        data_class=joined.effective_data_class,
        provenance="governed_context",
        trust_level=join_trust_levels(
            (joined.effective_trust_level, "untrusted_external")
        ),
        source_ref=observation.source_ref,
        source_revision=observation.source_revision,
        source_digest=observation.source_digest,
        resource_identity=observation.resource_identity,
        classification_revision=(
            RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION
            if proof_complete
            else None
        ),
    )


def _generalist_context_source_chunks(
    content: object,
) -> tuple[tuple[str, object], ...] | None:
    if not isinstance(content, dict):
        return None
    required = {
        "run_id",
        "status",
        "summary",
        "progress",
        "quality_gate",
        "tasks",
        "artifacts",
    }
    if set(content) != required:
        return None
    run_id = content.get("run_id")
    tasks = content.get("tasks")
    artifacts = content.get("artifacts")
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or not isinstance(tasks, list)
        or not isinstance(artifacts, list)
        or any(not isinstance(item, dict) for item in (*tasks, *artifacts))
    ):
        return None
    base_ref = f"inter-agent-run:{run_id}"
    chunks: list[tuple[str, object]] = [
        (
            f"{base_ref}:control",
            {
                "run_id": run_id,
                "status": content["status"],
                "progress": content["progress"],
                "quality_gate": content["quality_gate"],
                "task_count": len(tasks),
                "artifact_count": len(artifacts),
            },
        ),
        (f"{base_ref}:summary", {"summary": content["summary"]}),
    ]
    seen_task_ids: set[str] = set()
    for item in tasks:
        task_id = item.get("task_id")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or task_id in seen_task_ids
        ):
            return None
        seen_task_ids.add(task_id)
        chunks.append((f"{base_ref}:task:{task_id}", item))
    chunks.extend(
        (f"{base_ref}:artifact:{index}", item)
        for index, item in enumerate(artifacts)
    )
    return tuple(chunks)


def _expected_source_contract(source_id: str) -> tuple[str, str] | None:
    fixed = _FIXED_SOURCES.get(source_id)
    if fixed is not None:
        return fixed
    indexed = _INDEXED_SOURCE.fullmatch(source_id)
    if indexed is None:
        return None
    return _INDEXED_PROVENANCE[indexed.group(1)]


__all__ = [
    "RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION",
    "RUNTIME_PROVIDER_INPUT_RESOURCE_KIND",
    "GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND",
    "build_runtime_provider_input_classification_resolver",
    "classify_admitted_runtime_provider_input",
]
