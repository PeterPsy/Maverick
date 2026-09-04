"""Provider-neutral facade over authoritative CLI, MCP and interface surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from core.cli.command_registry import CliCommandRegistry
from core.egress.classification import CanonicalSourceClassification
from core.identity.models import PlatformRole
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_models import ToolEffectClass
from core.runtime.tool_result_classification import (
    RuntimeToolClassificationProjection,
)
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
    execution_control: object | None = field(
        default=None,
        compare=False,
        repr=False,
    )


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
    owner_kind: Literal["core", "app", "dynamic"] = "dynamic"
    schema_public: bool = False
    certified_tcb_component: str | None = None


@dataclass(frozen=True)
class RuntimeToolSurfaceResult:
    """Tool payload plus classification derived from the resource actually read."""

    payload: dict[str, object]
    classification: CanonicalSourceClassification
    classification_projection: RuntimeToolClassificationProjection | None = None

    def __post_init__(self) -> None:
        if self.classification_projection is not None:
            if not isinstance(
                self.classification_projection,
                RuntimeToolClassificationProjection,
            ):
                raise RuntimeToolError(
                    "tool_result_classification_projection_invalid"
                )
            self.classification_projection.resolve(self.payload)

    def __getitem__(self, key: str) -> object:
        return self.payload[key]

    def __contains__(self, key: object) -> bool:
        return key in self.payload


@dataclass(frozen=True)
class RuntimeToolRejection:
    """Structured fail-closed catalog decision retained before egress."""

    handle: str
    surface_kind: RuntimeToolSurfaceKind
    reason_code: str


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
    [dict[str, object], RuntimeToolActorContext, str | None],
    dict[str, object] | RuntimeToolSurfaceResult,
]
RuntimeToolResultClassificationResolver = Callable[
    [str, dict[str, object], dict[str, object], RuntimeToolActorContext],
    CanonicalSourceClassification | RuntimeToolSurfaceResult | None,
]


@dataclass(frozen=True)
class RuntimeToolResultPreflightDecision:
    """Whether a variable-result tool may cross its effect boundary."""

    admitted_before_effect: bool
    guaranteed_data_class: str | None = None


RuntimeToolResultPreflightResolver = Callable[
    [str, dict[str, object], RuntimeToolActorContext],
    RuntimeToolResultPreflightDecision | None,
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
    schema_owner_kind: str = "dynamic"
    schema_data_class: str = "unclassified"
    schema_trust_level: str = "untrusted_external"
    certified_tcb_component: str | None = None


@dataclass(frozen=True)
class RuntimeToolCatalog:
    """Immutable per-turn mapping between provider names and internal handles."""

    descriptors: tuple[RuntimeToolDescriptor, ...]
    rejections: tuple[RuntimeToolRejection, ...] = ()

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
        result_classification_resolver: RuntimeToolResultClassificationResolver | None = None,
        result_preflight_resolver: RuntimeToolResultPreflightResolver | None = None,
    ) -> None:
        self.cli_registry = cli_registry
        self.mcp_registry = mcp_registry
        self.app_interface_resolver = app_interface_resolver
        self.core_capabilities = core_capabilities
        self.result_classification_resolver = result_classification_resolver
        self.result_preflight_resolver = result_preflight_resolver

    def build(
        self,
        *,
        authority: EffectiveRuntimeAuthority,
        context: RuntimeToolActorContext,
    ) -> RuntimeToolCatalog:
        """Build the exact authorized catalog; unknown classifications fail closed."""
        if context.execution_mode != authority.execution_mode:
            raise RuntimeToolError("tool_execution_mode_mismatch")
        allowed = set(authority.allowed_tool_handles)
        if not authority.allowed_capabilities.tool_orchestration:
            return RuntimeToolCatalog(
                (),
                tuple(
                    RuntimeToolRejection(
                        handle,
                        self._surface_kind(handle),
                        "tool_capability_denied",
                    )
                    for handle in sorted(allowed)
                ),
            )
        descriptors: list[RuntimeToolDescriptor] = []
        rejections: list[RuntimeToolRejection] = []
        handled: set[str] = set()
        for definition in self.cli_registry.list_commands():
            handle = f"cli:{definition.command_id}"
            if handle not in allowed:
                continue
            handled.add(handle)
            if not authority.allowed_capabilities.cli:
                rejections.append(
                    RuntimeToolRejection(handle, "cli", "tool_capability_denied")
                )
                continue
            reason = self._rejection_reason(
                handle, allowed, definition.effect_class, definition.workspace_id, context
            )
            if reason is None:
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
                        schema_owner_kind=definition.owner_kind,
                        schema_data_class=(
                            "public" if definition.schema_public else "unclassified"
                        ),
                        schema_trust_level=(
                            "trusted_platform"
                            if definition.owner_kind == "core"
                            else "untrusted_external"
                        ),
                        certified_tcb_component=definition.certified_tcb_component,
                    )
                )
            else:
                rejections.append(RuntimeToolRejection(handle, "cli", reason))
        for definition in self.mcp_registry.list_tools():
            handle = f"mcp:{definition.tool_name}"
            if handle not in allowed:
                continue
            handled.add(handle)
            if not authority.allowed_capabilities.mcp:
                rejections.append(
                    RuntimeToolRejection(handle, "mcp", "tool_capability_denied")
                )
                continue
            reason = self._rejection_reason(
                handle, allowed, definition.effect_class, definition.workspace_id, context
            )
            if reason is None:
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
                        schema_owner_kind=definition.owner_kind,
                        schema_data_class=(
                            "public" if definition.schema_public else "unclassified"
                        ),
                        schema_trust_level=(
                            "trusted_platform"
                            if definition.owner_kind == "core"
                            else "untrusted_external"
                        ),
                        certified_tcb_component=definition.certified_tcb_component,
                    )
                )
            else:
                rejections.append(RuntimeToolRejection(handle, "mcp", reason))
        if self.app_interface_resolver is not None and any(
            handle.startswith("app-interface:") for handle in allowed
        ):
            for surface in self.app_interface_resolver.list_tool_surfaces(context=context):
                if not surface.handle.startswith("app-interface:"):
                    raise RuntimeToolError("tool_interface_handle_invalid")
                if surface.handle not in allowed:
                    continue
                handled.add(surface.handle)
                reason = self._rejection_reason(
                    surface.handle, allowed, surface.effect_class, context.workspace_id, context
                )
                if reason is None:
                    descriptors.append(self._external_descriptor(surface, "app-interface"))
                else:
                    rejections.append(
                        RuntimeToolRejection(surface.handle, "app-interface", reason)
                    )
        for surface in self.core_capabilities:
            definition = surface.definition
            if definition.handle not in allowed:
                continue
            handled.add(definition.handle)
            if authority.execution_mode not in surface.allowed_execution_modes:
                rejections.append(
                    RuntimeToolRejection(definition.handle, "core-capability", "tool_execution_mode_denied")
                )
                continue
            if not self._core_capability_allowed(definition.handle, authority):
                rejections.append(
                    RuntimeToolRejection(definition.handle, "core-capability", "tool_capability_denied")
                )
                continue
            reason = self._rejection_reason(
                definition.handle, allowed, definition.effect_class, context.workspace_id, context
            )
            if reason is None:
                descriptors.append(self._external_descriptor(definition, "core-capability"))
            else:
                rejections.append(RuntimeToolRejection(definition.handle, "core-capability", reason))
        for handle in sorted(allowed - handled):
            rejections.append(
                RuntimeToolRejection(handle, self._surface_kind(handle), "tool_not_found")
            )
        descriptors.sort(key=lambda item: item.handle)
        rejections.sort(key=lambda item: (item.handle, item.reason_code))
        names = [item.provider_name for item in descriptors]
        if len(names) != len(set(names)):
            raise RuntimeToolError("tool_name_mapping_collision")
        return RuntimeToolCatalog(tuple(descriptors), tuple(rejections))

    @staticmethod
    def _surface_kind(handle: str) -> RuntimeToolSurfaceKind:
        for prefix, kind in (
            ("cli:", "cli"),
            ("mcp:", "mcp"),
            ("app-interface:", "app-interface"),
            ("core-capability:", "core-capability"),
        ):
            if handle.startswith(prefix):
                return kind
        return "core-capability"

    @staticmethod
    def _rejection_reason(
        handle: str,
        allowed: set[str],
        effect_class: ToolEffectClass,
        definition_workspace_id: str | None,
        context: RuntimeToolActorContext,
    ) -> str | None:
        if handle not in allowed:
            return "tool_not_authorized"
        if effect_class == "unclassified":
            return "tool_effect_unclassified"
        if definition_workspace_id not in {None, context.workspace_id}:
            return "tool_workspace_mismatch"
        return None

    @staticmethod
    def _core_capability_allowed(handle: str, authority: EffectiveRuntimeAuthority) -> bool:
        capability = authority.allowed_capabilities
        return {
            "core-capability:workspace.instructions": capability.filesystem_read,
            "core-capability:filesystem.list": capability.filesystem_list,
            "core-capability:filesystem.search": capability.filesystem_read,
            "core-capability:filesystem.read": capability.filesystem_read,
            "core-capability:filesystem.write": capability.filesystem_write,
            "core-capability:filesystem.edit": capability.filesystem_write,
            "core-capability:filesystem.patch": capability.filesystem_write,
            "core-capability:filesystem.move": capability.filesystem_write,
            "core-capability:filesystem.delete": capability.filesystem_write,
            "core-capability:shell.run": capability.shell,
            "core-capability:process.start": capability.shell,
            "core-capability:process.status": capability.shell,
            "core-capability:process.input": capability.shell,
            "core-capability:process.interrupt": capability.shell,
            "core-capability:cli.list": capability.cli,
            "core-capability:cli.run": capability.cli,
            "core-capability:mcp.list": capability.mcp,
            "core-capability:mcp.call": capability.mcp,
            "core-capability:artifact.read": capability.filesystem_read,
        }.get(handle, False)

    def _external_descriptor(
        self, surface: RuntimeExternalToolSurface, kind: RuntimeToolSurfaceKind
    ) -> RuntimeToolDescriptor:
        # The app-interface boundary is app-owned by construction. An app may
        # describe its schema, but it cannot promote itself into the Core TCB by
        # setting declaration fields on RuntimeExternalToolSurface.
        app_owned = kind == "app-interface"
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
            schema_owner_kind="app" if app_owned else surface.owner_kind,
            schema_data_class=(
                "unclassified"
                if app_owned
                else ("public" if surface.schema_public else "unclassified")
            ),
            schema_trust_level=(
                "untrusted_external"
                if app_owned
                else (
                    "trusted_platform"
                    if surface.owner_kind == "core"
                    else "untrusted_external"
                )
            ),
            certified_tcb_component=(
                None if app_owned else surface.certified_tcb_component
            ),
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
        schema_owner_kind: str = "dynamic",
        schema_data_class: str = "unclassified",
        schema_trust_level: str = "untrusted_external",
        certified_tcb_component: str | None = None,
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
            schema_owner_kind=schema_owner_kind,
            schema_data_class=schema_data_class,
            schema_trust_level=schema_trust_level,
            certified_tcb_component=certified_tcb_component,
        )
