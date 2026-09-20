"""Entrypoint section parsing for app contracts."""

from __future__ import annotations

from pathlib import Path

from core.apps.contract_validation import _expect_mapping, _expect_relative_contract_path, _reject_unexpected_fields
from core.apps.models import AppEntrypoints
from core.apps.errors import AppContractValidationError


def parse_entrypoints_section(source_root: Path, payload: dict[str, object]) -> AppEntrypoints:
    mcp_entrypoint = payload.get("mcp")
    cli_entrypoint = payload.get("cli")
    backend_entrypoint = payload.get("backend")
    frontend_entrypoint = payload.get("frontend")
    skills_root = payload.get("skills_root")
    json_worker = payload.get("json_worker")
    _reject_unexpected_fields(payload, {"mcp", "cli", "backend", "frontend", "skills_root", "hooks", "json_worker"}, label="entrypoints")
    if json_worker is not None and mcp_entrypoint is None and backend_entrypoint is None:
        raise AppContractValidationError("`entrypoints.json_worker` requires a backend or MCP entrypoint.")
    if json_worker is not None and (not isinstance(json_worker, str) or not json_worker.strip()):
        raise AppContractValidationError("`entrypoints.json_worker` must be a non-empty relative path.")
    hooks_payload = _expect_mapping(payload.get("hooks", {}), label="entrypoints.hooks")
    hooks = {
        hook_name: _expect_relative_contract_path(source_root, hook_path, label=f"entrypoints.hooks.{hook_name}")
        for hook_name, hook_path in hooks_payload.items()
    }
    return AppEntrypoints(
        mcp=(
            _expect_relative_contract_path(source_root, mcp_entrypoint, label="entrypoints.mcp")
            if mcp_entrypoint is not None
            else None
        ),
        cli=(
            _expect_relative_contract_path(source_root, cli_entrypoint, label="entrypoints.cli")
            if cli_entrypoint is not None
            else None
        ),
        backend=(
            _expect_relative_contract_path(source_root, backend_entrypoint, label="entrypoints.backend")
            if backend_entrypoint is not None
            else None
        ),
        frontend=(
            _expect_relative_contract_path(
                source_root,
                frontend_entrypoint,
                label="entrypoints.frontend",
                allow_directory=True,
            )
            if frontend_entrypoint is not None
            else None
        ),
        skills_root=(
            _expect_relative_contract_path(source_root, skills_root, label="entrypoints.skills_root", allow_directory=True)
            if skills_root is not None
            else None
        ),
        hooks=hooks,
        json_worker=(
            _expect_relative_contract_path(source_root, json_worker, label="entrypoints.json_worker")
            if json_worker is not None else None
        ),
    )
