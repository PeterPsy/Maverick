"""Provider-neutral facade over authoritative CLI, MCP and interface surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from core.cli.command_registry import CliCommandRegistry
from core.identity.models import PlatformRole
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_models import ToolEffectClass
from core.runtime.tool_schema import provider_safe_tool_schema, provider_tool_name


RuntimeToolSurfaceKind = Literal["cli", "mcp", "app-interface", "core-capability"]


@dataclass(frozen=True)
class RuntimeToolActorContext:
    """Trusted actor and workspace context used by official invocation surfaces."""

    workspace_id: str
    actor_id: str
    agent_id: str | None
    platform_role: PlatformRole | None
    workspace_role: str | None
    session_id: str
    execution_mode: Literal["sandbox", "full-access"]
    consumer_app_id: str | None = None


@dataclass(frozen=True)
class RuntimeExternalToolSurface:
    """A generic app-interface or Core capability resolved by its owner."""

    handle: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    effect_class: ToolEffectClass
    supports_idempotency: bool = False
    safe_to_retry: bool = False


class RuntimeAppInterfaceResolver(Protocol):
    """Resolve and invoke selected app providers through the official boundary."""

    def list_tool_surfaces(
        self, *, context: RuntimeToolActorContext
    ) -> list[RuntimeExternalToolSurface]: ...

    def invoke_tool_surface(
        self,
        *,
        handle: str,
        arguments: dict[str, object],
        context: RuntimeToolActorContext,
        idempotency_key: str | None,
    ) -> dict[str, object]: ...


RuntimeCoreCapabilityHandler = Callable[
    [dict[str, object], RuntimeToolActorContext, str | None], dict[str, object]
]


@dataclass(frozen=True)
class RuntimeCoreCapabilitySurface:
    """A Core capability with an execution-policy-owned implementation."""

    definition: RuntimeExternalToolSurface
    handler: RuntimeCoreCapabilityHandler
    allowed_execution_modes: tuple[Literal["sandbox", "full-access"], ...]


@dataclass(frozen=True)
class RuntimeToolDescriptor:
    """One authorized descriptor exposed to a model for the current turn."""

    provider_name: str
    handle: str
    surface_kind: RuntimeToolSurfaceKind
    source_id: str
    description: str
    input_schema: dict[str, Any]
    original_input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    effect_class: ToolEffectClass
    supports_idempotency: bool
    safe_to_retry: bool


@dataclass(frozen=True)
class RuntimeToolCatalog:
    """Immutable per-turn mapping between provider names and internal handles."""

    descriptors: tuple[RuntimeToolDescriptor, ...]

    def by_provider_name(self, provider_name: str) -> RuntimeToolDescriptor:
        for descriptor in self.descriptors:
            if descriptor.provider_name == provider_name:
                return descriptor
        raise RuntimeToolError("tool_not_found")

    def by_handle(self, handle: str) -> RuntimeToolDescriptor:
        for descriptor in self.descriptors:
            if descriptor.handle == handle:
                return descriptor
        raise RuntimeToolError("tool_not_authorized")


class RuntimeToolCatalogBuilder:
    """Compose existing registries without copying their handlers or metadata."""

    def __init__(
        self,
        *,
        cli_registry: CliCommandRegistry,
        mcp_registry: McpToolRegistry,
        app_interface_resolver: RuntimeAppInterfaceResolver | None = None,
        core_capabilities: tuple[RuntimeCoreCapabilitySurface, ...] = (),
    ) -> None:
        self.cli_registry = cli_registry
        self.mcp_registry = mcp_registry
        self.app_interface_resolver = app_interface_resolver
        self.core_capabilities = core_capabilities

    def build(
        self,
        *,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
    ) -> RuntimeToolCatalog:
        """Build the exact authorized catalog; unknown classifications fail closed."""
        if context.execution_mode != authority.execution_mode:
            raise RuntimeToolError("tool_execution_mode_mismatch")
        if not authority.allowed_capabilities.tool_orchestration:
            return RuntimeToolCatalog(())
        allowed = set(authority.allowed_tool_handles)
        descriptors: list[RuntimeToolDescriptor] = []
        if authority.allowed_capabilities.cli:
            for definition in self.cli_registry.list_commands():
                handle = f"cli:{definition.command_id}"
                if self._visible(handle, allowed, definition.effect_class, definition.workspace_id, context):
                    descriptors.append(
                        self._descriptor(
                            handle=handle,
                            surface_kind="cli",
                            source_id=definition.command_id,
                            description=definition.description,
                            input_schema=definition.argument_schema,
                            output_schema=None,
                            effect_class=definition.effect_class,
                            supports_idempotency=definition.supports_idempotency,
                            safe_to_retry=definition.safe_to_retry,
                        )
                    )
        if authority.allowed_capabilities.mcp:
            for definition in self.mcp_registry.list_tools():
                handle = f"mcp:{definition.tool_name}"
                if self._visible(handle, allowed, definition.effect_class, definition.workspace_id, context):
                    descriptors.append(
                        self._descriptor(
                            handle=handle,
                            surface_kind="mcp",
                            source_id=definition.tool_name,
                            description=definition.description,
                            input_schema=definition.input_schema,
                            output_schema=definition.output_schema,
                            effect_class=definition.effect_class,
                            supports_idempotency=definition.supports_idempotency,
                            safe_to_retry=definition.safe_to_retry,
                        )
                    )
        if self.app_interface_resolver is not None:
            for surface in self.app_interface_resolver.list_tool_surfaces(context=context):
                if not surface.handle.startswith("app-interface:"):
                    raise RuntimeToolError("tool_interface_handle_invalid")
                if self._visible(surface.handle, allowed, surface.effect_class, context.workspace_id, context):
                    descriptors.append(self._external_descriptor(surface, "app-interface"))
        for surface in self.core_capabilities:
            definition = surface.definition
            if authority.execution_mode not in surface.allowed_execution_modes:
                continue
            if not self._core_capability_allowed(definition.handle, authority):
                continue
            if self._visible(definition.handle, allowed, definition.effect_class, context.workspace_id, context):
                descriptors.append(self._external_descriptor(definition, "core-capability"))
        descriptors.sort(key=lambda item: item.handle)
        names = [item.provider_name for item in descriptors]
        if len(names) != len(set(names)):
            raise RuntimeToolError("tool_name_mapping_collision")
        return RuntimeToolCatalog(tuple(descriptors))

    @staticmethod
    def _visible(
        handle: str,
        allowed: set[str],
        effect_class: ToolEffectClass,
        definition_workspace_id: str | None,
        context: RuntimeToolActorContext,
    ) -> bool:
        return (
            handle in allowed
            and effect_class != "unclassified"
            and definition_workspace_id in {None, context.workspace_id}
        )

    @staticmethod
    def _core_capability_allowed(handle: str, authority: EffectiveRuntimeAuthority) -> bool:
        capability = authority.allowed_capabilities
        return {
            "core-capability:filesystem.list": capability.filesystem_list,
            "core-capability:filesystem.read": capability.filesystem_read,
            "core-capability:filesystem.write": capability.filesystem_write,
            "core-capability:shell.run": capability.shell,
        }.get(handle, False)

    def _external_descriptor(
        self, surface: RuntimeExternalToolSurface, kind: RuntimeToolSurfaceKind
    ) -> RuntimeToolDescriptor:
        return self._descriptor(
            handle=surface.handle,
            surface_kind=kind,
            source_id=surface.handle,
            description=surface.description,
            input_schema=surface.input_schema,
            output_schema=surface.output_schema,
            effect_class=surface.effect_class,
            supports_idempotency=surface.supports_idempotency,
            safe_to_retry=surface.safe_to_retry,
        )

    @staticmethod
    def _descriptor(
        *,
        handle: str,
        surface_kind: RuntimeToolSurfaceKind,
        source_id: str,
        description: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any] | None,
        effect_class: ToolEffectClass,
        supports_idempotency: bool,
        safe_to_retry: bool,
    ) -> RuntimeToolDescriptor:
        return RuntimeToolDescriptor(
            provider_name=provider_tool_name(handle),
            handle=handle,
            surface_kind=surface_kind,
            source_id=source_id,
            description=description[:1024],
            input_schema=provider_safe_tool_schema(input_schema),
            original_input_schema=input_schema,
            output_schema=output_schema,
            effect_class=effect_class,
            supports_idempotency=supports_idempotency,
            safe_to_retry=safe_to_retry,
        )
