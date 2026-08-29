"""Certified JSON schemas for Full Workspace Core capabilities."""

from __future__ import annotations


def workspace_instructions_schema() -> dict[str, object]:
    return _object(
        {
            "path": _path(),
            "target_is_directory": {"type": "boolean"},
        },
        required=("path",),
    )


def filesystem_search_schema() -> dict[str, object]:
    return _object(
        {
            "path": _path(),
            "query": {"type": "string", "minLength": 1, "maxLength": 4096},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 8},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
            "cursor": {"type": "string", "minLength": 1, "maxLength": 16384},
            "case_sensitive": {"type": "boolean"},
        },
        required=("query",),
    )


def filesystem_edit_schema() -> dict[str, object]:
    return _object(
        {
            "path": _path(),
            "old_text": {"type": "string", "minLength": 1, "maxLength": 1_048_576},
            "new_text": {"type": "string", "maxLength": 1_048_576},
            "expected_occurrences": {"type": "integer", "minimum": 1, "maximum": 10_000},
            **_expected_version_properties(),
            **_instruction_digest_property(),
        },
        required=(
            "path",
            "old_text",
            "new_text",
            "expected_resource_identity",
            "expected_resource_revision",
            "instruction_scope_digest",
        ),
    )


def filesystem_patch_schema() -> dict[str, object]:
    operation = _object(
        {
            "old_text": {"type": "string", "minLength": 1, "maxLength": 1_048_576},
            "new_text": {"type": "string", "maxLength": 1_048_576},
            "expected_occurrences": {"type": "integer", "minimum": 1, "maximum": 10_000},
        },
        required=("old_text", "new_text"),
    )
    return _object(
        {
            "path": _path(),
            "operations": {
                "type": "array",
                "items": operation,
                "minItems": 1,
                "maxItems": 128,
            },
            **_expected_version_properties(),
            **_instruction_digest_property(),
        },
        required=(
            "path",
            "operations",
            "expected_resource_identity",
            "expected_resource_revision",
            "instruction_scope_digest",
        ),
    )


def filesystem_move_schema() -> dict[str, object]:
    return _object(
        {
            "source_path": _path(),
            "destination_path": _path(),
            "create_parents": {"type": "boolean"},
            "source_instruction_scope_digest": _instruction_digest_schema(),
            "destination_instruction_scope_digest": _instruction_digest_schema(),
            **_expected_version_properties(),
        },
        required=(
            "source_path",
            "destination_path",
            "expected_resource_identity",
            "expected_resource_revision",
            "source_instruction_scope_digest",
            "destination_instruction_scope_digest",
        ),
    )


def filesystem_delete_schema() -> dict[str, object]:
    return _object(
        {
            "path": _path(),
            "recursive": {"type": "boolean"},
            **_expected_version_properties(),
            **_instruction_digest_property(),
        },
        required=(
            "path",
            "expected_resource_identity",
            "expected_resource_revision",
            "instruction_scope_digest",
        ),
    )


def process_start_schema() -> dict[str, object]:
    return _object(
        {
            "argv": _argv(),
            "cwd": _path(),
            "timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3_600,
            },
            "mutation_scopes": workspace_mutation_scopes_schema(),
        },
        required=("argv", "mutation_scopes"),
    )


def workspace_mutation_scopes_schema() -> dict[str, object]:
    """Declare every instruction-governed directory eligible for COW commit."""
    return {
        "type": "array",
        "items": _object(
            {
                "path": _path(),
                "instruction_scope_digest": _instruction_digest_schema(),
            },
            required=("path", "instruction_scope_digest"),
        ),
        "maxItems": 32,
    }


def process_status_schema() -> dict[str, object]:
    return _object(
        {
            "process_id": _process_id(),
            "output_offset": {"type": "integer", "minimum": 0},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 131_072},
        },
        required=("process_id",),
    )


def process_input_schema() -> dict[str, object]:
    return _object(
        {
            "process_id": _process_id(),
            "content": {"type": "string", "maxLength": 65_536},
            "close": {"type": "boolean"},
        },
        required=("process_id", "content"),
    )


def process_interrupt_schema() -> dict[str, object]:
    return _object(
        {"process_id": _process_id()},
        required=("process_id",),
    )


def extended_filesystem_write_schema(max_bytes: int) -> dict[str, object]:
    return _object(
        {
            "path": _path(),
            "content": {"type": "string", "maxLength": max_bytes},
            "create_only": {"type": "boolean"},
            "replace_only": {"type": "boolean"},
            "create_parents": {"type": "boolean"},
            **_expected_version_properties(),
            **_instruction_digest_property(),
        },
        required=("path", "content", "instruction_scope_digest"),
    )


def _expected_version_properties() -> dict[str, object]:
    return {
        "expected_resource_identity": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
        },
        "expected_resource_revision": {
            "type": "string",
            "minLength": 64,
            "maxLength": 64,
        },
    }


def _instruction_digest_property() -> dict[str, object]:
    return {
        "instruction_scope_digest": _instruction_digest_schema()
    }


def _instruction_digest_schema() -> dict[str, object]:
    return {
        "type": "string",
        "minLength": 64,
        "maxLength": 64,
    }


def _argv() -> dict[str, object]:
    return {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        "minItems": 1,
        "maxItems": 64,
    }


def _path() -> dict[str, object]:
    return {"type": "string", "minLength": 1, "maxLength": 4096}


def _process_id() -> dict[str, object]:
    return {"type": "string", "minLength": 1, "maxLength": 128}


def _object(
    properties: dict[str, object],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema
