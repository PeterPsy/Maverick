"""Execution-policy-owned filesystem and shell runtime tool surfaces."""

from __future__ import annotations

from contextlib import suppress
import os
from pathlib import Path
import subprocess
import tempfile

from core.runtime.tool_catalog import (
    RuntimeCoreCapabilitySurface,
    RuntimeExternalToolSurface,
    RuntimeToolActorContext,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_filesystem_listing import (
    MAX_FILESYSTEM_LIST_DEPTH,
    MAX_FILESYSTEM_LIST_RESULTS,
    filesystem_list_schema,
    list_workspace_entries,
)


MAX_FILESYSTEM_READ_BYTES = 262_144
MAX_FILESYSTEM_WRITE_BYTES = 1_048_576
MAX_SHELL_OUTPUT_BYTES = 131_072
MAX_SHELL_TIMEOUT_SECONDS = 30


def build_core_runtime_tool_capabilities(
    *, workspace_id: str, workspace_root: Path
) -> tuple[RuntimeCoreCapabilitySurface, ...]:
    """Build workspace-bound Core capabilities; no app id is involved."""
    root = workspace_root.resolve(strict=True)

    def filesystem_list(
        arguments: dict[str, object], context: RuntimeToolActorContext, _idempotency_key: str | None
    ) -> dict[str, object]:
        _require_context(context, workspace_id)
        path = _workspace_path(root, arguments.get("path", "."), must_exist=True)
        if not path.is_dir():
            raise RuntimeToolError("filesystem_path_not_directory")
        max_depth = arguments.get("max_depth", 1)
        max_results = arguments.get("max_results", 200)
        if (
            not isinstance(max_depth, int)
            or isinstance(max_depth, bool)
            or not 1 <= max_depth <= MAX_FILESYSTEM_LIST_DEPTH
            or not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= MAX_FILESYSTEM_LIST_RESULTS
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        entries, truncated = list_workspace_entries(
            root,
            path,
            max_depth=max_depth,
            max_results=max_results,
        )
        relative_path = path.relative_to(root).as_posix()
        return {
            "path": relative_path or ".",
            "entries": entries,
            "result_count": len(entries),
            "truncated": truncated,
        }

    def filesystem_read(
        arguments: dict[str, object], context: RuntimeToolActorContext, _idempotency_key: str | None
    ) -> dict[str, object]:
        _require_context(context, workspace_id)
        path = _workspace_path(root, arguments.get("path"), must_exist=True)
        if not path.is_file():
            raise RuntimeToolError("filesystem_path_not_file")
        requested = arguments.get("max_bytes", MAX_FILESYSTEM_READ_BYTES)
        if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
            raise RuntimeToolError("tool_arguments_invalid")
        max_bytes = min(requested, MAX_FILESYSTEM_READ_BYTES)
        try:
            with path.open("rb") as handle:
                payload = handle.read(max_bytes + 1)
        except OSError as error:
            raise RuntimeToolError("filesystem_read_failed") from error
        if len(payload) > max_bytes:
            raise RuntimeToolError("filesystem_read_too_large")
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeToolError("filesystem_read_not_utf8") from error
        return {
            "path": path.relative_to(root).as_posix(),
            "content": content,
            "byte_count": len(payload),
        }

    def filesystem_write(
        arguments: dict[str, object], context: RuntimeToolActorContext, _idempotency_key: str | None
    ) -> dict[str, object]:
        _require_context(context, workspace_id)
        path = _workspace_path(root, arguments.get("path"), must_exist=False)
        content = arguments.get("content")
        if not isinstance(content, str):
            raise RuntimeToolError("tool_arguments_invalid")
        payload = content.encode("utf-8")
        if len(payload) > MAX_FILESYSTEM_WRITE_BYTES:
            raise RuntimeToolError("filesystem_write_too_large")
        if arguments.get("create_only") is True and path.exists():
            raise RuntimeToolError("filesystem_path_exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except OSError as error:
            raise RuntimeToolError("filesystem_write_failed") from error
        finally:
            if temporary_name is not None:
                with suppress(OSError):
                    Path(temporary_name).unlink(missing_ok=True)
        return {"path": path.relative_to(root).as_posix(), "byte_count": len(payload)}

    def shell_run(
        arguments: dict[str, object], context: RuntimeToolActorContext, _idempotency_key: str | None
    ) -> dict[str, object]:
        _require_context(context, workspace_id)
        if context.execution_mode != "full-access":
            raise RuntimeToolError("shell_requires_full_access")
        argv = arguments.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 64
            or any(not isinstance(item, str) or not item or len(item) > 4096 for item in argv)
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        cwd = _workspace_path(root, arguments.get("cwd", "."), must_exist=True)
        if not cwd.is_dir():
            raise RuntimeToolError("shell_cwd_invalid")
        timeout = arguments.get("timeout_seconds", MAX_SHELL_TIMEOUT_SECONDS)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_SHELL_TIMEOUT_SECONDS:
            raise RuntimeToolError("tool_arguments_invalid")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        }
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeToolError("shell_execution_failed") from error
        output = completed.stdout[: MAX_SHELL_OUTPUT_BYTES + 1]
        if len(output) > MAX_SHELL_OUTPUT_BYTES:
            raise RuntimeToolError("shell_output_too_large")
        return {
            "exit_code": completed.returncode,
            "output": output.decode("utf-8", errors="replace"),
            "output_bytes": len(output),
        }

    return (
        RuntimeCoreCapabilitySurface(
            definition=RuntimeExternalToolSurface(
                handle="core-capability:filesystem.list",
                description=(
                    "List bounded workspace-relative file and directory names without reading file content."
                ),
                input_schema=filesystem_list_schema(),
                output_schema=None,
                effect_class="read",
                safe_to_retry=True,
            ),
            handler=filesystem_list,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=RuntimeExternalToolSurface(
                handle="core-capability:filesystem.read",
                description="Read one bounded UTF-8 file using a workspace-relative path.",
                input_schema=_filesystem_read_schema(),
                output_schema=None,
                effect_class="read",
                safe_to_retry=True,
            ),
            handler=filesystem_read,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=RuntimeExternalToolSurface(
                handle="core-capability:filesystem.write",
                description="Atomically write one bounded UTF-8 file under the workspace root.",
                input_schema=_filesystem_write_schema(),
                output_schema=None,
                effect_class="mutating",
            ),
            handler=filesystem_write,
            allowed_execution_modes=("sandbox", "full-access"),
        ),
        RuntimeCoreCapabilitySurface(
            definition=RuntimeExternalToolSurface(
                handle="core-capability:shell.run",
                description="Run one argv command with a sanitized environment and workspace cwd.",
                input_schema=_shell_schema(),
                output_schema=None,
                effect_class="destructive",
            ),
            handler=shell_run,
            allowed_execution_modes=("full-access",),
        ),
    )


def _workspace_path(root: Path, value: object, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RuntimeToolError("filesystem_path_invalid")
    relative = Path(value)
    if relative.is_absolute():
        raise RuntimeToolError("filesystem_path_outside_workspace")
    try:
        resolved = (root / relative).resolve(strict=must_exist)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise RuntimeToolError("filesystem_path_outside_workspace") from error
    return resolved


def _require_context(context: RuntimeToolActorContext, workspace_id: str) -> None:
    if context.workspace_id != workspace_id:
        raise RuntimeToolError("tool_workspace_mismatch")


def _filesystem_read_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_FILESYSTEM_READ_BYTES},
        },
        "required": ["path"],
        "additionalProperties": False,
    }


def _filesystem_write_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "content": {"type": "string", "maxLength": MAX_FILESYSTEM_WRITE_BYTES},
            "create_only": {"type": "boolean"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }


def _shell_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                "minItems": 1,
                "maxItems": 64,
            },
            "cwd": {"type": "string", "minLength": 1, "maxLength": 4096},
            "timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SHELL_TIMEOUT_SECONDS,
            },
        },
        "required": ["argv"],
        "additionalProperties": False,
    }
