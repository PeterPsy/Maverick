"""Codex thread parameters for legacy and lean explicit sessions."""

from __future__ import annotations

from typing import Any

from core.device_use.contract import (
    DEVICE_USE_MODEL_ID,
    device_use_base_instructions,
    device_use_dynamic_tools,
)
from core.providers.codex_prompt_budget import (
    CODEX_EXPLICIT_BASE_INSTRUCTIONS,
    CODEX_EXPLICIT_PROJECT_DOC_MAX_BYTES,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.runtime_session import RuntimeSessionRecord


def codex_initialize_params(*, session: RuntimeSessionRecord) -> dict[str, Any]:
    params: dict[str, Any] = {
        "clientInfo": {"name": "maverick", "version": "3.0.0"},
    }
    if getattr(session, "device_use_binding", None) is not None:
        params["capabilities"] = {"experimentalApi": True}
    return params


def codex_thread_params(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
) -> dict[str, Any]:
    if getattr(session, "device_use_binding", None) is not None:
        binding = session.device_use_binding
        return {
            "model": DEVICE_USE_MODEL_ID,
            "modelProvider": "openai",
            "cwd": launch_spec.working_directory,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "environments": [],
            "dynamicTools": device_use_dynamic_tools(),
            "baseInstructions": device_use_base_instructions(
                approved_apps=binding.approved_apps,
                initial_app=binding.initial_app,
            ),
            "config": {"mcp_servers": {}, "project_doc_max_bytes": 0},
        }
    params = {
        "approvalPolicy": "never",
        "cwd": launch_spec.working_directory,
        "sandbox": "danger-full-access" if launch_spec.execution_mode == "full-access" else "read-only",
        "developerInstructions": session.system_prompt or "",
        "config": {"mcp_servers": {}},
    }
    if getattr(session, "skill_activation_mode", "implicit") == "explicit":
        params["baseInstructions"] = CODEX_EXPLICIT_BASE_INSTRUCTIONS
        params["config"]["project_doc_max_bytes"] = CODEX_EXPLICIT_PROJECT_DOC_MAX_BYTES
    return params
