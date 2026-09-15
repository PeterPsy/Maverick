"""Fixed isolation contract for web-only Research sessions."""

from __future__ import annotations

from dataclasses import replace

from core.providers.agentic_models import AgenticRuntimePolicy
from core.providers.errors import AgenticRuntimeError
from core.providers.execution_families import effective_agentic_execution_family
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from core.runtime.tool_catalog import RuntimeToolCatalog
from core.runtime.tool_schema_review import REVIEWED_TOOL_SCHEMA_COMPONENT


RESEARCH_WEB_TOOL_HANDLES = (
    "mcp:app.browser.web_search",
    "mcp:app.browser.web_open",
)
RESEARCH_HOSTED_WEB_RUNTIME = "hosted-web-tools-v1"
RESEARCH_NATIVE_WEB_RUNTIME = "native-web-only-v1"
_RESEARCH_PROVIDER_TOOL_NAMES = {
    "mcp:app.browser.web_search": "web_search",
    "mcp:app.browser.web_open": "web_open",
}
_RESEARCH_WEB_TOOL_SCHEMAS = {
    "mcp:app.browser.web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "mcp:app.browser.web_open": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


def runtime_session_is_research(session: object) -> bool:
    return getattr(session, "runtime_profile", "workspace") == "research"


def research_runtime_kind(binding: object, adapter: object) -> str | None:
    """Return the reviewed Research transport contract declared by an adapter."""
    runtime_engine_id = str(getattr(binding, "runtime_engine_id", "") or "")
    adapter_id = str(getattr(binding, "adapter_id", "") or "")
    if (
        runtime_engine_id != str(getattr(adapter, "runtime_engine_id", "") or "")
        or adapter_id != str(getattr(adapter, "adapter_id", "") or "")
    ):
        return None
    family = effective_agentic_execution_family(
        str(getattr(binding, "execution_family", "") or ""),
        runtime_engine_id=runtime_engine_id,
        adapter_id=adapter_id,
        model_provider_id=str(getattr(binding, "model_provider_id", "") or ""),
        provider_protocol=str(getattr(binding, "provider_protocol", "") or ""),
    )
    declared = str(getattr(adapter, "research_runtime_kind", "") or "")
    if family == "maverick_agent" and declared == RESEARCH_HOSTED_WEB_RUNTIME:
        return declared
    if family == "native_agent" and declared == RESEARCH_NATIVE_WEB_RUNTIME:
        attest = getattr(adapter, "research_runtime_available", None)
        if callable(attest) and attest(binding):
            return declared
    return None


def research_tool_candidates(
    base: tuple[str, ...],
    *,
    runtime_kind: str | None,
) -> tuple[str, ...]:
    if runtime_kind == RESEARCH_HOSTED_WEB_RUNTIME:
        return tuple(dict.fromkeys((*base, *RESEARCH_WEB_TOOL_HANDLES)))
    return ()


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
    """Expose the two reviewed, neutral Research web contracts."""
    if not runtime_session_is_research(session):
        return catalog
    return replace(
        catalog,
        descriptors=tuple(
            replace(
                descriptor,
                provider_name=_RESEARCH_PROVIDER_TOOL_NAMES[descriptor.handle],
                input_schema=_RESEARCH_WEB_TOOL_SCHEMAS[descriptor.handle],
                original_input_schema=_RESEARCH_WEB_TOOL_SCHEMAS[descriptor.handle],
                schema_owner_kind="core",
                schema_data_class="public",
                schema_trust_level="trusted_platform",
                reviewed_schema_component=REVIEWED_TOOL_SCHEMA_COMPONENT,
            )
            for descriptor in catalog.descriptors
            if descriptor.handle in _RESEARCH_PROVIDER_TOOL_NAMES
            and descriptor.surface_kind == "mcp"
            and descriptor.source_id == descriptor.handle.removeprefix("mcp:")
            and descriptor.effect_class == "read"
            and descriptor.original_input_schema
            == _RESEARCH_WEB_TOOL_SCHEMAS[descriptor.handle]
        ),
    )


def isolate_research_authority(
    authority: EffectiveRuntimeAuthority,
    *,
    runtime_kind: str | None,
) -> EffectiveRuntimeAuthority:
    """Remove every model-facing capability except the fixed web read tools."""
    handles = (
        tuple(
            handle
            for handle in RESEARCH_WEB_TOOL_HANDLES
            if handle in authority.allowed_tool_handles
        )
        if runtime_kind == RESEARCH_HOSTED_WEB_RUNTIME
        else ()
    )
    declared = authority.allowed_capabilities
    web_tools_available = (
        runtime_kind == RESEARCH_HOSTED_WEB_RUNTIME
        and declared.tool_orchestration
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
    *,
    adapter: object,
) -> None:
    capabilities = authority.allowed_capabilities
    runtime_kind = research_runtime_kind(binding, adapter)
    hosted_ready = (
        runtime_kind == RESEARCH_HOSTED_WEB_RUNTIME
        and authority.allowed_tool_handles == RESEARCH_WEB_TOOL_HANDLES
        and capabilities.tool_orchestration
        and capabilities.mcp
    )
    native_ready = (
        runtime_kind == RESEARCH_NATIVE_WEB_RUNTIME
        and authority.allowed_tool_handles == ()
        and not capabilities.tool_orchestration
        and not capabilities.cli
        and not capabilities.mcp
        and not capabilities.skill_catalog
        and not capabilities.filesystem_list
        and not capabilities.filesystem_read
        and not capabilities.filesystem_write
        and not capabilities.shell
        and not capabilities.confirmation_resume
        and capabilities.attachment_modalities == ()
        and not capabilities.app_references
        and not capabilities.confirmations
    )
    if authority.execution_mode != "full-access" or not (hosted_ready or native_ready):
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
