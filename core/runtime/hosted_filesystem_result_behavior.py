"""Executable filesystem workflows for the hosted result-contract gate."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace

from core.runtime.filesystem_mutation_lineage import (
    resolve_filesystem_mutation_lineage,
)
from core.runtime.public_content_authority import (
    build_runtime_public_content_authority_record,
)
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
)
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.hosted_behavior_probe_cache import cache_complete_behavior_probe
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_private_payloads import canonical_tool_arguments


FILESYSTEM_RESULT_BEHAVIOR_IDS = (
    "core-capability:filesystem.write:create",
    "core-capability:filesystem.write:replace",
    "core-capability:filesystem.edit",
    "core-capability:filesystem.patch",
    "core-capability:filesystem.move",
    "core-capability:filesystem.delete",
    "core-capability:filesystem.read-after-write",
)


@cache_complete_behavior_probe(FILESYSTEM_RESULT_BEHAVIOR_IDS)
def inspect_hosted_filesystem_result_behavior() -> tuple[str, ...]:
    """Execute version-fenced public-preimage workflows, including rereads."""
    try:
        with tempfile.TemporaryDirectory() as directory:
            return _inspect(Path(directory))
    except Exception:
        return ()


def _inspect(workspace_root: Path) -> tuple[str, ...]:
    paths = {
        "AGENTS.md": "Behavior probe instructions.\n",
        "replace.txt": "replace before\n",
        "edit.txt": "edit before\n",
        "patch.txt": "patch before\n",
        "move.txt": "move before\n",
        "delete.txt": "delete before\n",
    }
    for relative_path, content in paths.items():
        (workspace_root / relative_path).write_text(content, encoding="utf-8")

    authority = build_runtime_public_content_authority_record(
        workspace_id="behavior-probe",
        actor_id="core-behavior-probe",
        active=True,
    )

    def classify(observation, provenance):
        return classification_from_runtime_public_content_authority(
            authority,
            workspace_id=observation.workspace_id,
            provenance=provenance,
            trust_level="untrusted_tool_output",
            source_ref=observation.resource_ref,
            source_revision=observation.resource_revision,
            source_digest=observation.resource_digest,
            resource_identity=observation.resource_identity,
        )

    capabilities = _capabilities(workspace_root, classify)
    context = RuntimeToolActorContext(
        workspace_id="behavior-probe",
        actor_id="core",
        agent_id="behavior-probe",
        platform_role="admin",
        workspace_role="owner",
        session_id="behavior-probe",
        execution_mode="full-access",
    )
    instructions = capabilities[
        "core-capability:workspace.instructions"
    ].handler({"path": "replace.txt"}, context, None)
    scope_digest = str(instructions.payload["scope_digest"])
    verified: set[str] = set()

    created = capabilities["core-capability:filesystem.write"].handler(
        {
            "path": "created.txt",
            "content": "created by provider\n",
            "create_only": True,
            "instruction_scope_digest": scope_digest,
        },
        context,
        None,
    )
    rebuilt_after_create = _capabilities(workspace_root, classify)
    reread_created = _read(
        rebuilt_after_create,
        context,
        "created.txt",
    )
    if (
        _public_and_pairable(created)
        and _public_and_pairable(reread_created)
        and reread_created.payload.get("content") == "created by provider\n"
    ):
        verified.add("core-capability:filesystem.write:create")

    replaced, reread = _replace_workflow(
        capabilities,
        context,
        scope_digest,
        workspace_root,
        classify,
    )
    if _public_and_pairable(replaced):
        verified.add("core-capability:filesystem.write:replace")
    if _public_and_pairable(reread) and reread.payload.get("content") == "replace after\n":
        verified.add("core-capability:filesystem.read-after-write")

    edited = _edit_workflow(capabilities, context, scope_digest)
    if _public_and_pairable(edited):
        verified.add("core-capability:filesystem.edit")
    patched = _patch_workflow(capabilities, context, scope_digest)
    if _public_and_pairable(patched):
        verified.add("core-capability:filesystem.patch")
    moved = _move_workflow(capabilities, context, scope_digest)
    if _public_and_pairable(moved):
        verified.add("core-capability:filesystem.move")
    deleted = _delete_workflow(capabilities, context, scope_digest)
    if _public_and_pairable(deleted):
        verified.add("core-capability:filesystem.delete")
    return tuple(
        behavior
        for behavior in FILESYSTEM_RESULT_BEHAVIOR_IDS
        if behavior in verified
    )


def _replace_workflow(
    capabilities,
    context,
    scope_digest,
    workspace_root,
    authoritative_resolver,
):
    observed = _read(capabilities, context, "replace.txt")
    replaced = capabilities["core-capability:filesystem.write"].handler(
        {
            "path": "replace.txt",
            "content": "replace after\n",
            "replace_only": True,
            "expected_resource_identity": observed.payload["resource_identity"],
            "expected_resource_revision": observed.payload["resource_revision"],
            "instruction_scope_digest": scope_digest,
        },
        context,
        None,
    )
    rebuilt = _capabilities(
        workspace_root,
        _lineage_resolver(
            authoritative_resolver,
            context,
            "core-capability:filesystem.write",
            replaced,
        ),
    )
    return replaced, _read(rebuilt, context, "replace.txt")


def _edit_workflow(capabilities, context, scope_digest):
    observed = _read(capabilities, context, "edit.txt")
    edited = capabilities["core-capability:filesystem.edit"].handler(
        {
            "path": "edit.txt",
            "old_text": "before",
            "new_text": "after",
            "expected_resource_identity": observed.payload["resource_identity"],
            "expected_resource_revision": observed.payload["resource_revision"],
            "instruction_scope_digest": scope_digest,
        },
        context,
        None,
    )
    reread = _read(capabilities, context, "edit.txt")
    return edited if _public_and_pairable(reread) else None


def _patch_workflow(capabilities, context, scope_digest):
    observed = _read(capabilities, context, "patch.txt")
    patched = capabilities["core-capability:filesystem.patch"].handler(
        {
            "path": "patch.txt",
            "operations": [{"old_text": "before", "new_text": "after"}],
            "expected_resource_identity": observed.payload["resource_identity"],
            "expected_resource_revision": observed.payload["resource_revision"],
            "instruction_scope_digest": scope_digest,
        },
        context,
        None,
    )
    reread = _read(capabilities, context, "patch.txt")
    return patched if _public_and_pairable(reread) else None


def _move_workflow(capabilities, context, scope_digest):
    observed = _read(capabilities, context, "move.txt")
    moved = capabilities["core-capability:filesystem.move"].handler(
        {
            "source_path": "move.txt",
            "destination_path": "moved.txt",
            "expected_resource_identity": observed.payload["resource_identity"],
            "expected_resource_revision": observed.payload["resource_revision"],
            "source_instruction_scope_digest": scope_digest,
            "destination_instruction_scope_digest": scope_digest,
        },
        context,
        None,
    )
    reread = _read(capabilities, context, "moved.txt")
    return moved if _public_and_pairable(reread) else None


def _delete_workflow(capabilities, context, scope_digest):
    observed = _read(capabilities, context, "delete.txt")
    return capabilities["core-capability:filesystem.delete"].handler(
        {
            "path": "delete.txt",
            "expected_resource_identity": observed.payload["resource_identity"],
            "expected_resource_revision": observed.payload["resource_revision"],
            "instruction_scope_digest": scope_digest,
        },
        context,
        None,
    )


def _read(capabilities, context, path):
    return capabilities["core-capability:filesystem.read"].handler(
        {"path": path},
        context,
        None,
    )


def _public_and_pairable(result) -> bool:
    if not isinstance(result, RuntimeToolSurfaceResult):
        return False
    paired = pairing_safe_tool_result(
        result.payload,
        is_error=False,
        result_data_class=result.classification.data_class,
        allowed_remote_data_classes=("public",),
    )
    return result.classification.data_class == "public" and paired == (
        result.payload,
        False,
    )


def _capabilities(workspace_root, classification_resolver):
    return {
        surface.definition.handle: surface
        for surface in build_core_runtime_tool_capabilities(
            workspace_id="behavior-probe",
            workspace_root=workspace_root,
            resource_classification_resolver=classification_resolver,
        )
    }


def _lineage_resolver(authoritative_resolver, context, handle, result):
    result_digest = hashlib.sha256(
        canonical_tool_arguments(result.payload)
    ).hexdigest()
    record = SimpleNamespace(
        invocation_id="behavior-probe-mutation",
        workspace_id=context.workspace_id,
        session_id=context.session_id,
        state="succeeded",
        resolved_tool_handle=handle,
        result_data_class=result.classification.data_class,
        result_trust_level=result.classification.trust_level,
        result_provenance="tool_result",
        result_classification_revision=(
            result.classification.classification_revision
        ),
        result_classification_authority_id=(
            result.classification.classification_authority_id
        ),
        result_classification_authority_kind=(
            result.classification.classification_authority_kind
        ),
        result_classification_authority_ref=(
            result.classification.classification_authority_ref
        ),
        result_classification_authority_revision=(
            result.classification.classification_authority_revision
        ),
        result_classification_authority_digest=(
            result.classification.classification_authority_digest
        ),
        result_classification_authority_policy_revision=(
            result.classification.classification_authority_policy_revision
        ),
        result_classification_authority_bound=(
            result.classification.classification_authority_bound
        ),
        result_source_revision=result_digest,
        result_source_digest=result_digest,
        result_artifact_private_ref=None,
    )
    ledger = _BehaviorLedger(record, result.payload)

    def classify(observation, provenance):
        return resolve_filesystem_mutation_lineage(
            observation=observation,
            provenance=provenance,
            authoritative=authoritative_resolver(observation, provenance),
            ledger=ledger,
            session_id=context.session_id,
        )

    return classify


class _BehaviorLedger:
    def __init__(self, record, result):
        self._record = record
        self._result = dict(result)
        self.store = SimpleNamespace(
            list_tool_invocations=self._list_tool_invocations
        )

    def _list_tool_invocations(self, *, session_id):
        return [self._record] if session_id == self._record.session_id else []

    def load_result(self, record):
        if record.invocation_id != self._record.invocation_id:
            raise KeyError(record.invocation_id)
        return dict(self._result)


__all__ = [
    "FILESYSTEM_RESULT_BEHAVIOR_IDS",
    "inspect_hosted_filesystem_result_behavior",
]
