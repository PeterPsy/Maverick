"""Codex thread parameters for legacy and lean explicit sessions."""

from __future__ import annotations

from typing import Any

from core.device_use.contract import (
    device_use_base_instructions,
    device_use_dynamic_tools,
)
from core.providers.codex_prompt_budget import (
    CODEX_EXPLICIT_BASE_INSTRUCTIONS,
    CODEX_EXPLICIT_PROJECT_DOC_MAX_BYTES,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.research_runtime import (
    RESEARCH_BOUNDARY_INSTRUCTION,
    runtime_session_is_research,
)
from core.runtime.runtime_session import RuntimeSessionRecord


CODEX_RESEARCH_DISABLED_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "in_app_local_automation",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "personality",
    "plugins",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "sleep_tool",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
)
CODEX_RESEARCH_ENABLED_FEATURES = (
    "code_mode_host",
    "skip_host_skill_discovery",
)


def codex_research_config() -> dict[str, Any]:
    """Return the native Codex web-only configuration with no local context."""
    return {
        "web_search": "live",
        "project_doc_max_bytes": 0,
        "include_permissions_instructions": False,
        "include_apps_instructions": False,
        "include_collaboration_mode_instructions": False,
        "include_environment_context": False,
        "mcp_servers": {},
        "features": {
            **{
                feature: False for feature in CODEX_RESEARCH_DISABLED_FEATURES
            },
            **{
                feature: True for feature in CODEX_RESEARCH_ENABLED_FEATURES
            },
        },
        "skills": {
            "bundled": {"enabled": False},
            "include_instructions": False,
        },
        "tools": {
            "experimental_request_user_input": {"enabled": False},
            "update_plan": {"enabled": False},
        },
    }


def codex_initialize_params(*, session: RuntimeSessionRecord) -> dict[str, Any]:
    research = runtime_session_is_research(session)
    params: dict[str, Any] = {
        "clientInfo": {
            "name": "research-client" if research else "maverick",
            "version": "1.0.0" if research else "3.0.0",
        },
    }
    if (
        getattr(session, "device_use_binding", None) is not None
        or research
    ):
        params["capabilities"] = {"experimentalApi": True}
    return params


def codex_thread_params(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
) -> dict[str, Any]:
    if runtime_session_is_research(session):
        return {
            "cwd": launch_spec.working_directory,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            # Research keeps one private Codex archive per Maverick chat so a
            # later process can resume the same isolated conversation.
            "ephemeral": False,
            "environments": [],
            "baseInstructions": RESEARCH_BOUNDARY_INSTRUCTION,
            "developerInstructions": "",
            "personality": "none",
            "config": codex_research_config(),
        }
    if getattr(session, "device_use_binding", None) is not None:
        binding = session.device_use_binding
        execution_binding = getattr(session, "execution_binding", None)
        model_id = str(getattr(execution_binding, "model_id", "") or "").strip()
        if not model_id:
            raise ValueError("Device Use requires a pinned Codex model")
        return {
            "model": model_id,
            "modelProvider": "openai",
            "cwd": launch_spec.working_directory,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "environments": [],
            "dynamicTools": device_use_dynamic_tools(),
            "baseInstructions": device_use_base_instructions(
                mode=binding.mode,
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
