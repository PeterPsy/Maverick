"""Shared support for certified Full Workspace capability surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import PurePosixPath

from core.egress.classification import (
    CanonicalSourceClassification,
    join_classifications,
)
from core.runtime.tool_catalog import (
    RuntimeCoreCapabilitySurface,
    RuntimeExternalToolSurface,
    RuntimeToolActorContext,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.workspace_instructions import (
    resolve_workspace_instruction_chain_for_path,
    workspace_instruction_scope_digest,
)


MAX_EDIT_FILE_BYTES = 1_048_576
MAX_DIFF_BYTES = 65_536
CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT = "tool-schema-catalog"


@dataclass(frozen=True)
class MutationInstructionGuard:
    """Bind one model-read instruction snapshot to the actual mutation commit."""

    filesystem: object
    workspace_root: object
    path: str
    target_is_directory: bool
    expected_digest: str
    initial_chain: tuple[object, ...]
    affected_instruction_prefixes: tuple[str, ...] = ()

    @property
    def evidence(self) -> dict[str, object]:
        return _instruction_evidence(self.initial_chain, self.expected_digest)

    def verify_before(self) -> None:
        chain = self._resolve()
        if workspace_instruction_scope_digest(chain) != self.expected_digest:
            raise RuntimeToolError("workspace_instruction_scope_changed")

    def verify_after(self) -> None:
        chain = self._resolve()
        if not self.affected_instruction_prefixes:
            if workspace_instruction_scope_digest(chain) != self.expected_digest:
                raise RuntimeToolError("workspace_instruction_scope_changed")
            return
        before = _unaffected_instruction_snapshot(
            self.initial_chain,
            self.affected_instruction_prefixes,
        )
        after = _unaffected_instruction_snapshot(
            chain,
            self.affected_instruction_prefixes,
        )
        if before != after:
            raise RuntimeToolError("workspace_instruction_scope_changed")

    def _resolve(self):
        return resolve_workspace_instruction_chain_for_path(
            self.filesystem,
            workspace_root=self.workspace_root,
            relative_path=self.path,
            target_is_directory=self.target_is_directory,
        )


@dataclass(frozen=True)
class CombinedMutationInstructionGuard:
    guards: tuple[MutationInstructionGuard, ...]

    def verify_before(self) -> None:
        for guard in self.guards:
            guard.verify_before()

    def verify_after(self) -> None:
        for guard in self.guards:
            guard.verify_after()


def commit_text_change(
    filesystem,
    *,
    path,
    before,
    after,
    expected_identity,
    expected_revision,
    evidence,
    mutation_guard,
    operation_count,
):
    if before == after:
        raise RuntimeToolError("filesystem_edit_no_change")
    if len(after.encode("utf-8")) > MAX_EDIT_FILE_BYTES:
        raise RuntimeToolError("filesystem_write_too_large")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise RuntimeToolError("filesystem_diff_too_large")
    written = filesystem.write_text(
        path,
        content=after,
        create_only=False,
        create_parents=False,
        replace_only=True,
        expected_resource_identity=expected_identity,
        expected_resource_revision=expected_revision,
        mutation_guard=mutation_guard,
    )
    payload = {
        **written.payload,
        **evidence,
        "operation_count": operation_count,
        "diff": diff,
        "diff_bytes": len(diff.encode("utf-8")),
    }
    # write_text binds the proven pre-image taint to the exact committed
    # post-image.  Persist that observation with the mutation result so a later
    # hosted orchestrator can reconstruct read-after-write lineage.
    return RuntimeToolSurfaceResult(payload, written.classification)


def prepare_mutation_instruction_guard(
    filesystem,
    *,
    workspace_root,
    path,
    expected_digest,
    target_is_directory=None,
    affected_instruction_prefixes=(),
):
    if (
        not isinstance(expected_digest, str)
        or len(expected_digest) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_digest)
    ):
        raise RuntimeToolError("tool_arguments_invalid")
    if target_is_directory is None:
        try:
            target_is_directory = filesystem.path_is_directory(path)
        except RuntimeToolError as error:
            if error.reason_code != "filesystem_path_not_found":
                raise
            target_is_directory = False
    chain = resolve_workspace_instruction_chain_for_path(
        filesystem,
        workspace_root=workspace_root,
        relative_path=path,
        target_is_directory=target_is_directory,
    )
    digest_value = workspace_instruction_scope_digest(chain)
    if expected_digest.lower() != digest_value:
        raise RuntimeToolError("workspace_instruction_scope_changed")
    normalized_prefixes = tuple(
        _normalized_instruction_prefix(value)
        for value in affected_instruction_prefixes
    )
    return MutationInstructionGuard(
        filesystem=filesystem,
        workspace_root=workspace_root,
        path=path,
        target_is_directory=bool(target_is_directory),
        expected_digest=digest_value,
        initial_chain=chain,
        affected_instruction_prefixes=normalized_prefixes,
    )


def mutation_affected_instruction_prefixes(path, *, target_is_directory):
    """Return instruction paths intentionally changed by this target effect."""
    normalized = _normalized_instruction_prefix(path)
    if target_is_directory or PurePosixPath(normalized).name == "AGENTS.md":
        return (normalized,)
    return ()


def _instruction_evidence(chain, digest_value):
    return {
        "instruction_scope_digest": digest_value,
        "instruction_paths": [item.relative_path for item in chain],
        "instruction_revisions": [item.resource_revision for item in chain],
    }


def _normalized_instruction_prefix(value):
    raw = str(value or "").strip()
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or path.as_posix() != raw
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeToolError("tool_arguments_invalid")
    return raw


def _unaffected_instruction_snapshot(chain, affected_prefixes):
    return tuple(
        (
            item.relative_path,
            item.resource_identity,
            item.resource_revision,
            item.resource_digest,
        )
        for item in chain
        if not any(
            item.relative_path == prefix
            or item.relative_path.startswith(prefix.rstrip("/") + "/")
            for prefix in affected_prefixes
        )
    )


def instruction_classification(chain, digest_value):
    if not chain:
        return CanonicalSourceClassification(
            data_class="public",
            provenance="tool_result",
            trust_level="trusted_platform",
            source_ref="workspace-instructions:none",
            source_revision=digest_value,
            source_digest=digest_value,
            resource_identity="workspace-instructions:none",
            classification_revision=1,
        )
    joined = join_classifications(item.classification for item in chain)
    revisions = tuple(item.classification_revision for item in joined.sources)
    return CanonicalSourceClassification(
        data_class=joined.effective_data_class,
        provenance="tool_result",
        trust_level=joined.effective_trust_level,
        source_ref="workspace-instructions",
        source_revision=digest_value,
        source_digest=digest_value,
        resource_identity="workspace-instructions:" + digest_value,
        classification_revision=(
            max(revisions) if all(item is not None for item in revisions) else None
        ),
    )


def full_workspace_surface(
    name,
    description,
    schema,
    effect_class,
    handler,
    *,
    modes=("sandbox", "full-access"),
):
    return RuntimeCoreCapabilitySurface(
        definition=RuntimeExternalToolSurface(
            handle=f"core-capability:{name}",
            description=description,
            input_schema=schema,
            output_schema=None,
            effect_class=effect_class,
            safe_to_retry=effect_class == "read",
            owner_kind="core",
            schema_public=True,
            certified_tcb_component=CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT,
        ),
        handler=handler,
        allowed_execution_modes=modes,
    )


def require_workspace_context(
    context: RuntimeToolActorContext,
    workspace_id: str,
) -> None:
    if context.workspace_id != workspace_id:
        raise RuntimeToolError("tool_workspace_mismatch")


def argv_argument(value):
    invalid_item = (
        any(
            not isinstance(item, str) or not item or len(item) > 4096
            for item in value
        )
        if isinstance(value, list)
        else True
    )
    if not isinstance(value, list) or not value or len(value) > 64 or invalid_item:
        raise RuntimeToolError("tool_arguments_invalid")
    return value


def integer_argument(value, *, minimum, maximum=None):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise RuntimeToolError("tool_arguments_invalid")
    return value


def required_string(value, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RuntimeToolError("tool_arguments_invalid")
    return value


def optional_string(value):
    if value is None:
        return None
    return required_string(value)
