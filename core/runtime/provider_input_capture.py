"""Atomic, content-derived classification capture for transient turn input."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.attachment_projection import RuntimeAttachmentReadFence
from core.runtime.content_data_classification import classify_runtime_content
from core.runtime.public_content_authority import (
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION,
    runtime_public_content_authority_is_active,
)
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
)
from core.runtime.provider_input_governed_sources import (
    generalist_context_source_chunks,
)


RUNTIME_PROVIDER_INPUT_CAPTURE_REVISION = 1
RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION = 4
RUNTIME_PROVIDER_INPUT_CLASSIFIER_ID = "core-runtime-input-classifier-v4"
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
    attachment_read_fence: RuntimeAttachmentReadFence | None = None


def capture_runtime_provider_input_classifications(
    runtime_store,
    *,
    workspace_id: str,
    session_id: str,
    turn_id: str,
    sources: tuple[RuntimeProviderInputCaptureSource, ...],
    public_content_authority=None,
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
    try:
        classification_content_by_id = {
            source.source_id: _classification_content(source)
            for source in sources
        }
    except (TypeError, ValueError) as error:
        raise ValueError("runtime_provider_input_capture_invalid") from error
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
                    classification_content=content,
                    resource_kind=GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
                    resource_ref=resource_ref,
                    public_content_authority=public_content_authority,
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
            classification_content=classification_content_by_id[
                source.source_id
            ],
            resource_kind=RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
            resource_ref=f"runtime-turn:{turn_id}:{source.source_id}",
            public_content_authority=public_content_authority,
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
    classification_content: object,
    resource_kind: str,
    resource_ref: str,
    public_content_authority,
) -> dict[str, object]:
    encoded = canonical_egress_content(content)
    digest = hashlib.sha256(encoded).hexdigest()
    identity = (
        f"runtime-input:{workspace_id}:{session_id}:{turn_id}:"
        f"{source_id}:{digest}"
        if resource_kind == RUNTIME_PROVIDER_INPUT_RESOURCE_KIND
        else f"governed-context-source:{workspace_id}:{resource_ref}:{digest}"
    )
    data_class = classify_runtime_provider_input_content(
        classification_content,
        content_type=content_type,
        workspace_id=workspace_id,
        provenance=provenance,
        trust_level=(
            "trusted_actor"
            if provenance in {"agent_instruction", "user_input"}
            else "untrusted_external"
        ),
        source_ref=resource_ref,
        source_revision=digest,
        source_digest=digest,
        resource_identity=identity,
        public_content_authority=public_content_authority,
    )
    trust_level = (
        "trusted_actor"
        if provenance in {"agent_instruction", "user_input"}
        else "untrusted_external"
    )
    entry = {
        "resource_kind": resource_kind,
        "resource_ref": resource_ref,
        "resource_identity": identity,
        "resource_revision": digest,
        "resource_digest": digest,
        "data_class": data_class,
        "trust_level": trust_level,
        "classification_revision": RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION,
    }
    if runtime_public_content_authority_is_active(
        public_content_authority,
        workspace_id=workspace_id,
    ):
        entry.update(
            {
                "classification_authority_id": (
                    public_content_authority.classification_id
                ),
                "classification_authority_revision": (
                    public_content_authority.revision
                ),
                "classification_authority_digest": (
                    public_content_authority.resource_digest
                ),
                "classification_authority_policy_revision": (
                    RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION
                ),
            }
        )
    return entry


def _classification_content(
    source: RuntimeProviderInputCaptureSource,
) -> object:
    fence = source.attachment_read_fence
    if fence is None:
        return source.content
    if (
        source.provenance != "attachment"
        or not source.source_id.startswith("attachment:")
        or _INDEXED_SOURCE.fullmatch(source.source_id) is None
    ):
        raise ValueError("runtime_provider_input_capture_invalid")
    return fence.classification_projection(source.content)


def classify_runtime_provider_input_content(
    content: object,
    *,
    content_type: str,
    workspace_id: str = "",
    provenance: str = "user_input",
    trust_level: str = "trusted_actor",
    source_ref: str = "",
    source_revision: str = "",
    source_digest: str = "",
    resource_identity: str = "",
    public_content_authority=None,
) -> str:
    """Return a conservative class, promoted only by explicit authority."""
    detected = classify_runtime_content(content, content_type=content_type)
    authority = classification_from_runtime_public_content_authority(
        public_content_authority,
        workspace_id=workspace_id,
        provenance=provenance,
        trust_level=trust_level,
        source_ref=source_ref,
        source_revision=source_revision,
        source_digest=source_digest,
        resource_identity=resource_identity,
        detected_data_class=detected,
    )
    return (
        authority.data_class
        if authority.classification_revision is not None
        else detected
    )


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
