"""Shared support for certified Full Workspace capability surfaces."""

from __future__ import annotations

import difflib
import hashlib
import json

from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
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


def commit_text_change(
    filesystem,
    *,
    path,
    before,
    after,
    expected_identity,
    expected_revision,
    evidence,
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
    )
    payload = {
        **written.payload,
        **evidence,
        "operation_count": operation_count,
        "diff": diff,
        "diff_bytes": len(diff.encode("utf-8")),
    }
    return RuntimeToolSurfaceResult(payload, written.classification)


def mutation_instruction_evidence(
    filesystem,
    *,
    workspace_root,
    path,
    expected_digest,
    target_is_directory=None,
):
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
    if expected_digest is not None and expected_digest != digest_value:
        raise RuntimeToolError("workspace_instruction_scope_changed")
    return {
        "instruction_scope_digest": digest_value,
        "instruction_paths": [item.relative_path for item in chain],
        "instruction_revisions": [item.resource_revision for item in chain],
    }


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


def unclassified_process_result(result, session_id):
    result_digest = digest(result)
    return RuntimeToolSurfaceResult(
        result,
        fail_closed_classification(
            provenance="tool_result",
            source_ref="hosted-process",
            source_revision=result_digest,
            source_digest=result_digest,
            resource_identity=f"hosted-process:{session_id}",
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


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
