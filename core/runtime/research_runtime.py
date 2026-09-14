"""Fixed isolation contract for web-only Research sessions."""

from __future__ import annotations

from dataclasses import replace

from core.providers.agentic_models import AgenticRuntimePolicy
from core.providers.errors import AgenticRuntimeError
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from core.runtime.tool_catalog import RuntimeToolCatalog


RESEARCH_WEB_TOOL_HANDLES = (
    "mcp:app.browser.web_search",
    "mcp:app.browser.web_open",
)
_RESEARCH_PROVIDER_TOOL_NAMES = {
    "mcp:app.browser.web_search": "web_search",
    "mcp:app.browser.web_open": "web_open",
}


def runtime_session_is_research(session: object) -> bool:
    return getattr(session, "runtime_profile", "workspace") == "research"


def research_tool_candidates(base: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*base, *RESEARCH_WEB_TOOL_HANDLES)))


def research_runtime_policy(base: AgenticRuntimePolicy) -> AgenticRuntimePolicy:
    """Narrow one live policy to the immutable read-only web surface."""
    return replace(
        base,
        allowed_surface_kinds=("mcp",),
        tool_handle_mode="exact",
        allowed_tool_handles=RESEARCH_WEB_TOOL_HANDLES,
        allow_filesystem_list=False,
        allow_filesystem_read=False,
        allow_filesystem_write=False,
        allow_shell=False,
    )


def research_provider_catalog(
    session: object,
    catalog: RuntimeToolCatalog,
) -> RuntimeToolCatalog:
    """Expose neutral provider names without leaking Maverick internals."""
    if not runtime_session_is_research(session):
        return catalog
    return replace(
        catalog,
        descriptors=tuple(
            replace(
                descriptor,
                provider_name=_RESEARCH_PROVIDER_TOOL_NAMES[descriptor.handle],
            )
            for descriptor in catalog.descriptors
            if descriptor.handle in _RESEARCH_PROVIDER_TOOL_NAMES
        ),
    )


def isolate_research_authority(
    authority: EffectiveRuntimeAuthority,
) -> EffectiveRuntimeAuthority:
    """Remove every model-facing capability except the fixed web read tools."""
    handles = tuple(
        handle
        for handle in RESEARCH_WEB_TOOL_HANDLES
        if handle in authority.allowed_tool_handles
    )
    declared = authority.allowed_capabilities
    web_tools_available = (
        declared.tool_orchestration
        and declared.mcp
        and handles == RESEARCH_WEB_TOOL_HANDLES
    )
    capabilities = replace(
        declared,
        tool_orchestration=web_tools_available,
        cli=False,
        mcp=web_tools_available,
        skill_catalog=False,
        filesystem_list=False,
        filesystem_read=False,
        filesystem_write=False,
        shell=False,
        confirmation_resume=False,
        attachment_modalities=(),
        app_references=False,
        confirmations=False,
    )
    narrowed = replace(
        authority,
        allowed_capabilities=capabilities,
        allowed_tool_handles=handles if web_tools_available else (),
        authority_digest="",
    )
    return replace(narrowed, authority_digest=canonical_digest(narrowed))


def validate_research_authority(
    binding: RuntimeExecutionBinding,
    authority: EffectiveRuntimeAuthority,
) -> None:
    capabilities = authority.allowed_capabilities
    if (
        binding.runtime_engine_id != "maverick-tool-loop"
        or authority.execution_mode != "full-access"
        or authority.allowed_tool_handles != RESEARCH_WEB_TOOL_HANDLES
        or not capabilities.tool_orchestration
        or not capabilities.mcp
    ):
        raise AgenticRuntimeError("research_runtime_unavailable")


def assert_research_runtime_input_allowed(
    session: object,
    *,
    attachments: object = (),
    app_references: object = (),
    invoked_skill_ids: object = (),
) -> None:
    if not runtime_session_is_research(session):
        return
    if (
        getattr(session, "system_prompt", None)
        or getattr(session, "skill_ids", ())
        or getattr(session, "skill_catalog_app_id", None)
        or attachments
        or app_references
        or invoked_skill_ids
    ):
        raise AgenticRuntimeError("research_runtime_blocks_workspace_context")
