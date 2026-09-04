"""Full Workspace filesystem and instruction capability surfaces."""

from __future__ import annotations

from pathlib import Path

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.tool_catalog import (
    RuntimeCoreCapabilitySurface,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_full_workspace_schemas import (
    filesystem_delete_schema,
    filesystem_edit_schema,
    filesystem_move_schema,
    filesystem_patch_schema,
    filesystem_search_schema,
    workspace_instructions_schema,
)
from core.runtime.tool_full_workspace_support import (
    CombinedMutationInstructionGuard,
    MAX_EDIT_FILE_BYTES,
    commit_text_change as _commit_text_change,
    full_workspace_surface as _surface,
    instruction_classification as _instruction_classification,
    integer_argument as _integer,
    mutation_affected_instruction_prefixes,
    prepare_mutation_instruction_guard,
    optional_string as _optional_string,
    require_workspace_context as _require_context,
    required_string as _required_string,
)
from core.runtime.tool_process_capabilities import (
    build_process_capabilities as _process_surfaces,
)
from core.runtime.tool_result_classification import (
    RuntimeToolClassificationProjection,
)
from core.runtime.workspace_instructions import (
    read_complete_confined_text,
    resolve_workspace_instruction_chain_for_path,
    workspace_instruction_scope_digest,
)


def build_full_workspace_capabilities(
    *,
    filesystem: ConfinedWorkspaceFilesystem,
    workspace_root: Path,
    runtime_root: Path,
    process_registry: HostedToolProcessRegistry | None,
    result_classification_resolver=None,
) -> tuple[RuntimeCoreCapabilitySurface, ...]:
    """Build additional workspace surfaces over the shared filesystem anchor."""

    def instructions(arguments, context, _idempotency_key):
        _require_context(context, filesystem.workspace_id)
        path = str(arguments.get("path") or "")
        chain = resolve_workspace_instruction_chain_for_path(
            filesystem,
            workspace_root=workspace_root,
            relative_path=path,
            target_is_directory=arguments.get("target_is_directory") is True,
        )
        digest = workspace_instruction_scope_digest(chain)
        payload = {
            "path": path,
            "scope_digest": digest,
            "instructions": [
                {
                    "path": item.relative_path,
                    "scope": item.scope_path,
                    "content": item.content,
                    "resource_identity": item.resource_identity,
                    "resource_revision": item.resource_revision,
                    "resource_digest": item.resource_digest,
                }
                for item in chain
            ],
        }
        classification_paths = [("scope_digest",)]
        classification_paths.extend(
            ("instructions", index, field_name)
            for index in range(len(payload["instructions"]))
            for field_name in (
                "resource_identity",
                "resource_revision",
                "resource_digest",
            )
        )
        return _projected_core_result(
            payload,
            _instruction_classification(chain, digest),
            omitted_paths=tuple(classification_paths),
        )

    def search(arguments, context, _idempotency_key):
        _require_context(context, filesystem.workspace_id)
        result = filesystem.search_text(
            str(arguments.get("path") or "."),
            query=str(arguments.get("query") or ""),
            max_depth=_integer(arguments.get("max_depth", 4), minimum=1, maximum=8),
            page_size=_integer(arguments.get("max_results", 100), minimum=1, maximum=500),
            cursor=_optional_string(arguments.get("cursor")),
            case_sensitive=arguments.get("case_sensitive") is not False,
        )
        return _projected_core_result(
            result.payload,
            result.classification,
            omitted_paths=tuple(
                (field_name,)
                for field_name in (
                    "next_cursor",
                    "snapshot_id",
                    "resource_identity",
                    "resource_revision",
                    "resource_digest",
                )
            ),
        )

    def edit(arguments, context, _idempotency_key):
        _require_context(context, filesystem.workspace_id)
        path = _required_string(arguments.get("path"))
        expected_identity = _required_string(
            arguments.get("expected_resource_identity")
        )
        expected_revision = _required_string(
            arguments.get("expected_resource_revision")
        )
        current = read_complete_confined_text(
            filesystem,
            path,
            max_bytes=MAX_EDIT_FILE_BYTES,
        )
        if (
            current.payload["resource_identity"] != expected_identity
            or current.payload["resource_revision"] != expected_revision
        ):
            raise RuntimeToolError("filesystem_resource_changed")
        old_text = _required_string(arguments.get("old_text"), allow_empty=False)
        new_text = _required_string(arguments.get("new_text"), allow_empty=True)
        expected_count = _integer(
            arguments.get("expected_occurrences", 1),
            minimum=1,
            maximum=10_000,
        )
        content = str(current.payload["content"])
        actual_count = content.count(old_text)
        if actual_count != expected_count:
            raise RuntimeToolError("filesystem_edit_match_count_mismatch")
        replacement = content.replace(old_text, new_text)
        guard = prepare_mutation_instruction_guard(
            filesystem,
            workspace_root=workspace_root,
            path=path,
            expected_digest=_required_string(
                arguments.get("instruction_scope_digest")
            ),
            affected_instruction_prefixes=(
                mutation_affected_instruction_prefixes(
                    path,
                    target_is_directory=False,
                )
            ),
        )
        return _commit_text_change(
            filesystem,
            path=path,
            before=content,
            after=replacement,
            expected_identity=expected_identity,
            expected_revision=expected_revision,
            evidence=guard.evidence,
            mutation_guard=guard,
            operation_count=actual_count,
        )

    def patch(arguments, context, _idempotency_key):
        _require_context(context, filesystem.workspace_id)
        path = _required_string(arguments.get("path"))
        expected_identity = _required_string(
            arguments.get("expected_resource_identity")
        )
        expected_revision = _required_string(
            arguments.get("expected_resource_revision")
        )
        operations = arguments.get("operations")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 128:
            raise RuntimeToolError("tool_arguments_invalid")
        current = read_complete_confined_text(
            filesystem,
            path,
            max_bytes=MAX_EDIT_FILE_BYTES,
        )
        if (
            current.payload["resource_identity"] != expected_identity
            or current.payload["resource_revision"] != expected_revision
        ):
            raise RuntimeToolError("filesystem_resource_changed")
        content = str(current.payload["content"])
        replacement = content
        changed = 0
        for operation in operations:
            if not isinstance(operation, dict):
                raise RuntimeToolError("tool_arguments_invalid")
            old_text = _required_string(operation.get("old_text"))
            new_text = _required_string(operation.get("new_text"), allow_empty=True)
            expected_count = _integer(
                operation.get("expected_occurrences", 1),
                minimum=1,
                maximum=10_000,
            )
            actual_count = replacement.count(old_text)
            if actual_count != expected_count:
                raise RuntimeToolError("filesystem_patch_match_count_mismatch")
            replacement = replacement.replace(old_text, new_text)
            changed += actual_count
        guard = prepare_mutation_instruction_guard(
            filesystem,
            workspace_root=workspace_root,
            path=path,
            expected_digest=_required_string(
                arguments.get("instruction_scope_digest")
            ),
            affected_instruction_prefixes=(
                mutation_affected_instruction_prefixes(
                    path,
                    target_is_directory=False,
                )
            ),
        )
        return _commit_text_change(
            filesystem,
            path=path,
            before=content,
            after=replacement,
            expected_identity=expected_identity,
            expected_revision=expected_revision,
            evidence=guard.evidence,
            mutation_guard=guard,
            operation_count=changed,
        )

    def move(arguments, context, _idempotency_key):
        _require_context(context, filesystem.workspace_id)
        source = _required_string(arguments.get("source_path"))
        destination = _required_string(arguments.get("destination_path"))
        source_is_directory = filesystem.path_is_directory(source)
        affected_source = mutation_affected_instruction_prefixes(
            source,
            target_is_directory=source_is_directory,
        )
        affected_destination = mutation_affected_instruction_prefixes(
            destination,
            target_is_directory=source_is_directory,
        )
        affected_instruction_prefixes = tuple(
            dict.fromkeys((*affected_source, *affected_destination))
        )
        source_guard = prepare_mutation_instruction_guard(
            filesystem,
            workspace_root=workspace_root,
            path=source,
            expected_digest=_required_string(
                arguments.get("source_instruction_scope_digest")
            ),
            target_is_directory=source_is_directory,
            affected_instruction_prefixes=affected_instruction_prefixes,
        )
        destination_guard = prepare_mutation_instruction_guard(
            filesystem,
            workspace_root=workspace_root,
            path=destination,
            expected_digest=_required_string(
                arguments.get("destination_instruction_scope_digest")
            ),
            target_is_directory=source_is_directory,
            affected_instruction_prefixes=affected_instruction_prefixes,
        )
        guard = CombinedMutationInstructionGuard(
            (source_guard, destination_guard)
        )
        result = filesystem.move_path(
            source,
            destination,
            expected_resource_identity=_required_string(
                arguments.get("expected_resource_identity")
            ),
            expected_resource_revision=_required_string(
                arguments.get("expected_resource_revision")
            ),
            create_parents=arguments.get("create_parents") is True,
            mutation_guard=guard,
        )
        payload = {
            **result.payload,
            "source_instruction_scope": source_guard.evidence,
            "destination_instruction_scope": destination_guard.evidence,
        }
        return _projected_core_result(
            payload,
            result.classification,
            omitted_paths=(
                ("resource_identity",),
                ("resource_revision",),
                ("resource_digest",),
                ("source_instruction_scope", "instruction_scope_digest"),
                ("source_instruction_scope", "instruction_revisions"),
                (
                    "destination_instruction_scope",
                    "instruction_scope_digest",
                ),
                ("destination_instruction_scope", "instruction_revisions"),
            ),
        )

    def delete(arguments, context, _idempotency_key):
        _require_context(context, filesystem.workspace_id)
        path = _required_string(arguments.get("path"))
        target_is_directory = filesystem.path_is_directory(path)
        guard = prepare_mutation_instruction_guard(
            filesystem,
            workspace_root=workspace_root,
            path=path,
            expected_digest=_required_string(
                arguments.get("instruction_scope_digest")
            ),
            target_is_directory=target_is_directory,
            affected_instruction_prefixes=(
                mutation_affected_instruction_prefixes(
                    path,
                    target_is_directory=target_is_directory,
                )
            ),
        )
        result = filesystem.delete_path(
            path,
            expected_resource_identity=_required_string(
                arguments.get("expected_resource_identity")
            ),
            expected_resource_revision=_required_string(
                arguments.get("expected_resource_revision")
            ),
            recursive=arguments.get("recursive") is True,
            mutation_guard=guard,
        )
        payload = {**result.payload, **guard.evidence}
        return _projected_core_result(
            payload,
            result.classification,
            omitted_paths=(
                ("resource_identity",),
                ("resource_revision",),
                ("resource_digest",),
                ("instruction_scope_digest",),
                ("instruction_revisions",),
            ),
        )

    surfaces = [
        _surface("workspace.instructions", "Read applicable root-to-target AGENTS.md instructions and a mutation scope digest.", workspace_instructions_schema(), "read", instructions),
        _surface("filesystem.search", "Search a stable paginated UTF-8 workspace snapshot.", filesystem_search_schema(), "read", search),
        _surface("filesystem.edit", "Apply one exact version-fenced text replacement and return its diff.", filesystem_edit_schema(), "mutating", edit),
        _surface("filesystem.patch", "Apply ordered exact replacements atomically and return their diff.", filesystem_patch_schema(), "mutating", patch),
        _surface("filesystem.move", "Atomically rename one version-fenced workspace path without overwrite.", filesystem_move_schema(), "mutating", move),
        _surface("filesystem.delete", "Delete one version-fenced workspace path, optionally recursively.", filesystem_delete_schema(), "destructive", delete),
    ]
    if process_registry is not None:
        surfaces.extend(
            _process_surfaces(
                process_registry,
                filesystem=filesystem,
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                result_classification_resolver=result_classification_resolver,
            )
        )
    return tuple(surfaces)


def _projected_core_result(
    payload: dict[str, object],
    classification,
    *,
    omitted_paths: tuple[tuple[str | int, ...], ...],
) -> RuntimeToolSurfaceResult:
    return RuntimeToolSurfaceResult(
        payload,
        classification,
        RuntimeToolClassificationProjection.bind(
            payload,
            omitted_paths=omitted_paths,
        ),
    )
