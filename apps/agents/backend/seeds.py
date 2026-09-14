"""One-time retirement of obsolete bundled agent definitions."""

from __future__ import annotations

from pathlib import Path

from store import (
    AgentsValidationError,
    common_prompt_path,
    delete_role,
    ensure_data_root,
    list_agent_types,
    list_roles,
    write_agent_types,
)


RETIRED_AGENT_TYPE_IDS = frozenset(
    {
        "agent-type-agent-builder",
        "agent-type-backend-systems-engineer",
        "agent-type-business-intelligence-strategist",
        "agent-type-ceo-business-chief-of-staff",
        "agent-type-cfo-strategist",
        "agent-type-cmo-strategist",
        "agent-type-code-review-auditor",
        "agent-type-company-os-orchestrator",
        "agent-type-dynamic-product-price-researcher",
        "agent-type-frontend-design-engineer",
        "agent-type-general-operator",
        "agent-type-loopino-website-engineer",
        "agent-type-platform-verifier",
        "agent-type-role-creator",
        "agent-type-server-coding-engineer",
        "agent-type-social-video-content-strategist",
    }
)
RETIRED_ROLE_IDS = frozenset(
    {
        *(agent_type_id.removeprefix("agent-type-") for agent_type_id in RETIRED_AGENT_TYPE_IDS),
        "piero-linkedin-content-os",
        "test1-mopstt3l",
        "versy-design-analyst",
        "versy-media-creative-direction",
    }
)
_RETIREMENT_MARKER = ".legacy-agent-catalog-retired-v1"


def retire_legacy_catalog(data_root: Path) -> dict[str, int]:
    """Delete the exact historical catalog once while preserving future custom agents."""
    ensure_data_root(data_root)
    marker = data_root / _RETIREMENT_MARKER
    if marker.is_file():
        return {"retired_agent_type_count": 0, "retired_role_count": 0}
    agent_types = list_agent_types(data_root)
    retained_agent_types = [
        item for item in agent_types if item["id"] not in RETIRED_AGENT_TYPE_IDS
    ]
    retired_agent_types = len(agent_types) - len(retained_agent_types)
    if retired_agent_types:
        write_agent_types(data_root, retained_agent_types)
    retired_roles = 0
    existing_role_ids = {role["id"] for role in list_roles(data_root)}
    for role_id in RETIRED_ROLE_IDS & existing_role_ids:
        try:
            retired_roles += delete_role(data_root, role_id)
        except AgentsValidationError:
            # A retained custom agent may intentionally reference an old role id.
            continue
    common_prompt_path(data_root).write_text("", encoding="utf-8")
    marker.write_text("retired\n", encoding="utf-8")
    return {
        "retired_agent_type_count": retired_agent_types,
        "retired_role_count": retired_roles,
    }


def seed_defaults(data_root: Path) -> dict:
    ensure_data_root(data_root)
    retired = retire_legacy_catalog(data_root)
    return {
        "role_count": len(list_roles(data_root)),
        "agent_type_count": len(list_agent_types(data_root)),
        **retired,
    }
