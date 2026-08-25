"""Codex thread parameters for legacy and lean explicit sessions."""

from __future__ import annotations

from typing import Any

from core.providers.codex_prompt_budget import (
    CODEX_EXPLICIT_BASE_INSTRUCTIONS,
    CODEX_EXPLICIT_PROJECT_DOC_MAX_BYTES,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.runtime_session import RuntimeSessionRecord


def codex_thread_params(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
) -> dict[str, Any]:
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
