"""Atomic, content-derived classification capture for transient turn input."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.content_data_classification import classify_runtime_content
from core.runtime.provider_input_governed_sources import (
    generalist_context_source_chunks,
)


RUNTIME_PROVIDER_INPUT_CAPTURE_REVISION = 1
RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION = 2
RUNTIME_PROVIDER_INPUT_CLASSIFIER_ID = "core-runtime-input-classifier-v2"
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


@dataclass(frozen=True)
class RuntimeProviderInputCaptureSource:
    """Canonical bytes and composer identity captured before provider dispatch."""

    source_id: str
    provenance: str
    content_type: str
    content: object


def capture_runtime_provider_input_classifications(
    runtime_store,
    *,
    workspace_id: str,
    session_id: str,
    turn_id: str,
    sources: tuple[RuntimeProviderInputCaptureSource, ...],
) -> dict[str, object]:
    """Classify and persist the complete source manifest with one turn CAS."""
    turn = runtime_store.get_turn(turn_id)
    session = runtime_store.get_session(session_id)
    if (
        turn.workspace_id != workspace_id
        or turn.session_id != session_id
        or session.workspace_id != workspace_id
        or not sources
    ):
        raise ValueError("runtime_provider_input_capture_invalid")
    if any(
        not isinstance(source, RuntimeProviderInputCaptureSource)
        or not isinstance(source.source_id, str)
        or runtime_provider_input_source_contract(source.source_id)
        != (source.provenance, source.content_type)
        for source in sources
    ):
        raise ValueError("runtime_provider_input_capture_invalid")
    source_by_id = {source.source_id: source for source in sources}
    if len(source_by_id) != len(sources):
        raise ValueError("runtime_provider_input_capture_invalid")
    prompt = source_by_id.get("turn-prompt")
    if prompt is not None and prompt.content != turn.input_text:
        raise ValueError("runtime_provider_input_capture_invalid")
    instruction = source_by_id.get("agent-instruction")
    if instruction is not None and instruction.content != (
        session.system_prompt or ""
    ):
        raise ValueError("runtime_provider_input_capture_invalid")
    entries: dict[str, dict[str, object]] = {}
    for source in sources:
        if source.source_id == "generalist-orchestration":
            chunks = generalist_context_source_chunks(source.content)
            if chunks is None:
                raise ValueError("runtime_provider_input_capture_invalid")
            for resource_ref, content in chunks:
                entry = _classification_entry(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    source_id=source.source_id,
                    provenance="governed_context",
                    content_type="application/json",
                    content=content,
                    resource_kind=GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
                    resource_ref=resource_ref,
                )
                _insert_unique(entries, entry)
            continue
        entry = _classification_entry(
            workspace_id=workspace_id,
            session_id=session_id,
            turn_id=turn_id,
            source_id=source.source_id,
            provenance=source.provenance,
            content_type=source.content_type,
            content=source.content,
            resource_kind=RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
            resource_ref=f"runtime-turn:{turn_id}:{source.source_id}",
        )
        _insert_unique(entries, entry)
    manifest: dict[str, object] = {
        "schema_revision": RUNTIME_PROVIDER_INPUT_CAPTURE_REVISION,
        "classifier_id": RUNTIME_PROVIDER_INPUT_CLASSIFIER_ID,
        "classifier_revision": RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "sources": {key: entries[key] for key in sorted(entries)},
    }
    runtime_store.capture_turn_provider_input_classification_manifest(
        turn_id=turn_id,
        manifest=manifest,
    )
    return manifest


def _classification_entry(
    *,
    workspace_id: str,
    session_id: str,
    turn_id: str,
    source_id: str,
    provenance: str,
    content_type: str,
    content: object,
    resource_kind: str,
    resource_ref: str,
) -> dict[str, object]:
    encoded = canonical_egress_content(content)
    digest = hashlib.sha256(encoded).hexdigest()
    data_class = classify_runtime_provider_input_content(
        content,
        content_type=content_type,
    )
    trust_level = (
        "trusted_actor"
        if provenance in {"agent_instruction", "user_input"}
        else "untrusted_external"
    )
    identity = (
        f"runtime-input:{workspace_id}:{session_id}:{turn_id}:"
        f"{source_id}:{digest}"
        if resource_kind == RUNTIME_PROVIDER_INPUT_RESOURCE_KIND
        else f"governed-context-source:{workspace_id}:{resource_ref}:{digest}"
    )
    return {
        "resource_kind": resource_kind,
        "resource_ref": resource_ref,
        "resource_identity": identity,
        "resource_revision": digest,
        "resource_digest": digest,
        "data_class": data_class,
        "trust_level": trust_level,
        "classification_revision": RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION,
    }


def classify_runtime_provider_input_content(
    content: object,
    *,
    content_type: str,
) -> str:
    """Return a conservative class selected from the exact captured bytes."""
    return classify_runtime_content(content, content_type=content_type)


def runtime_provider_input_source_contract(
    source_id: str,
) -> tuple[str, str] | None:
    """Return the closed provenance/content contract accepted by the writer."""
    fixed = _FIXED_SOURCES.get(source_id)
    if fixed is not None:
        return fixed
    indexed = _INDEXED_SOURCE.fullmatch(source_id)
    if indexed is None:
        return None
    return _INDEXED_PROVENANCE[indexed.group(1)]


def _insert_unique(
    entries: dict[str, dict[str, object]],
    entry: dict[str, object],
) -> None:
    resource_ref = str(entry["resource_ref"])
    if resource_ref in entries:
        raise ValueError("runtime_provider_input_capture_invalid")
    entries[resource_ref] = entry


__all__ = [
    "GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND",
    "RUNTIME_PROVIDER_INPUT_CAPTURE_REVISION",
    "RUNTIME_PROVIDER_INPUT_CLASSIFIER_ID",
    "RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION",
    "RUNTIME_PROVIDER_INPUT_RESOURCE_KIND",
    "RuntimeProviderInputCaptureSource",
    "capture_runtime_provider_input_classifications",
    "classify_runtime_provider_input_content",
    "runtime_provider_input_source_contract",
]
