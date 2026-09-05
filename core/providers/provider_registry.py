"""Provider registry and runtime adapter contracts."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable, Protocol

from core.providers.errors import ProviderNotFoundError
from core.providers.models import ProviderDefinition, ProviderSubscriptionUsage, RuntimeBackendLaunchSpec, RuntimeSteerResult
from core.runtime.runtime_session import RuntimeSessionRecord

if TYPE_CHECKING:
    from core.providers.agentic_adapter import AgenticRuntimeEngineAdapter
    from core.providers.native_agent_contract import (
        NativeAgentInstallation,
        NativeRuntimeStatus,
    )
    from core.providers.native_agent_runtime import NativeAgentRuntimeController
    from core.runtime.execution import RuntimeExecutionResult
    from core.runtime.execution_events import RuntimeExecutionEventSink
    from core.skills.models import SkillDefinition, SkillMaterialization


class RuntimeBackendAdapter(Protocol):
    """Contract implemented by concrete runtime backend adapters."""

    def provider_definition(self) -> ProviderDefinition:
        ...

    def validate_backend(self) -> None:
        ...

    def build_launch_spec(
        self,
        session: RuntimeSessionRecord,
        *,
        secret_env: dict[str, str] | None = None,
        credential_binding_id: str | None = None,
        resolved_secret_refs: list[str] | None = None,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
    ) -> RuntimeBackendLaunchSpec:
        ...

    def prepare_runtime_skills(
        self,
        session: RuntimeSessionRecord,
        skills: list["SkillDefinition"],
    ) -> list["SkillMaterialization"]:
        ...

    def execute_turn(
        self,
        *,
        session: RuntimeSessionRecord,
        launch_spec: RuntimeBackendLaunchSpec,
        input_text: str,
        invoked_skills: list["SkillDefinition"] | None = None,
        event_sink: "RuntimeExecutionEventSink | None" = None,
        timeout_seconds: int | None = None,
        on_provider_thread_id: Callable[[str], None] | None = None,
        on_provider_startup_event: Callable[[str, dict[str, object]], None] | None = None,
        on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
        on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
        command_runner: Callable[..., Any] | None = None,
    ) -> "RuntimeExecutionResult":
        ...

    def close_runtime(self, session_id: str) -> int | None:
        ...

    def interrupt_turn(self, session_id: str) -> bool:
        ...

    def steer_turn(
        self,
        session_id: str,
        *,
        input_text: str,
        client_message_id: str | None = None,
        expected_provider_turn_id: str | None = None,
        invoked_skills: list["SkillDefinition"] | None = None,
        skill_activation_mode: str = "implicit",
    ) -> RuntimeSteerResult:
        ...

    def build_recovery_command(
        self,
        *,
        repository_root: Path,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
        command_override: str | None = None,
    ) -> list[str]:
        ...


class SubscriptionUsageAdapter(Protocol):
    """Optional contract for providers backed by subscription usage limits."""

    def read_subscription_usage(self) -> ProviderSubscriptionUsage:
        ...


class ProviderRegistry:
    """In-memory registry for provider definitions and runtime adapters."""

    def __init__(self) -> None:
        self._definitions: dict[str, ProviderDefinition] = {}
        self._runtime_adapters: dict[str, RuntimeBackendAdapter] = {}
        self._agentic_runtime_adapters: dict[str, AgenticRuntimeEngineAdapter] = {}
        self._native_agent_installations: dict[str, NativeAgentInstallation] = {}
        self._native_agent_controllers: dict[str, NativeAgentRuntimeController] = {}
        self.native_catalog_lock = RLock()
        self._native_agent_catalogs = {}
        self._native_catalog_reconciliations = {}

    def get_native_agent_catalog(self, runtime_engine_id: str, model_provider_id: str):
        """Read only snapshots published by the trusted discovery/reconcile path."""
        with self.native_catalog_lock:
            return self._native_agent_catalogs.get((runtime_engine_id, model_provider_id))

    def publish_native_agent_catalog(self, snapshot) -> None:
        with self.native_catalog_lock:
            installation = self.get_native_agent_installation(snapshot.runtime_engine_id)
            if not any(connection.model_provider_id == snapshot.model_provider_id
                       and connection.catalog_provider_id == snapshot.catalog_provider_id
                       for connection in installation.model_provider_connections):
                raise ValueError("native_agent_catalog_connection_mismatch")
            self._native_agent_catalogs[(snapshot.runtime_engine_id, snapshot.model_provider_id)] = snapshot

    def clear_native_agent_catalog(self, runtime_engine_id: str, model_provider_id: str) -> None:
        with self.native_catalog_lock:
            self._native_agent_catalogs.pop((runtime_engine_id, model_provider_id), None)
            self._native_catalog_reconciliations.pop((runtime_engine_id, model_provider_id), None)

    def register_provider_definition(self, definition: ProviderDefinition) -> ProviderDefinition:
        """Register one provider definition without a runtime adapter."""
        with self.native_catalog_lock:
            installation = self._native_agent_installations.get(definition.provider_id)
            if installation is not None and not installation.certification_configured:
                definition = replace(definition, status="disabled")
            self._definitions[definition.provider_id] = definition
            return definition

    def register_runtime_adapter(self, adapter: RuntimeBackendAdapter) -> ProviderDefinition:
        """Register one runtime backend adapter and its canonical definition."""
        definition = self.register_provider_definition(adapter.provider_definition())
        self._runtime_adapters[definition.provider_id] = adapter
        from core.providers.provider_legacy_agentic_bridge import LegacyRuntimeBackendAgenticBridge

        self._agentic_runtime_adapters[definition.provider_id] = LegacyRuntimeBackendAgenticBridge(adapter)
        return definition

    def register_native_agent_installation(
        self,
        installation: "NativeAgentInstallation",
        *,
        definition: ProviderDefinition,
        runtime_adapter: RuntimeBackendAdapter | None = None,
    ) -> ProviderDefinition:
        """Register a validated native adapter/recipe/connection certificate.

        Candidate registrations are clamped to disabled even if persisted
        provider metadata later attempts to activate them.
        """
        from core.providers.native_agent_contract import (
            validate_native_agent_installation,
            validate_native_runtime_adapter,
        )

        validate_native_agent_installation(installation)
        manifest = installation.manifest
        if definition.provider_id != manifest.runtime_engine_id:
            raise ValueError("native_agent_provider_identity_mismatch")
        if runtime_adapter is not None:
            validate_native_runtime_adapter(installation, runtime_adapter)
            adapter_definition = runtime_adapter.provider_definition()
            if adapter_definition.provider_id != manifest.runtime_engine_id:
                raise ValueError("native_agent_adapter_identity_mismatch")
            if str(getattr(runtime_adapter, "adapter_id", "")) != manifest.adapter_id:
                raise ValueError("native_agent_adapter_identity_mismatch")
            if str(getattr(runtime_adapter, "adapter_version", "")) != manifest.adapter_version:
                raise ValueError("native_agent_adapter_version_mismatch")
        elif installation.certification_configured:
            raise ValueError("native_agent_certified_adapter_missing")
        self._native_agent_installations[manifest.runtime_engine_id] = installation
        if runtime_adapter is not None:
            definition = self.register_runtime_adapter(runtime_adapter)
            from core.providers.native_agent_runtime import NativeAgentRuntimeController

            controller = NativeAgentRuntimeController(
                installation=installation,
                engine_adapter=self._agentic_runtime_adapters[
                    manifest.runtime_engine_id
                ],
                legacy_adapter=runtime_adapter,
            )
            self._native_agent_controllers[manifest.runtime_engine_id] = controller
            self._agentic_runtime_adapters[manifest.runtime_engine_id] = controller
            return definition
        return self.register_provider_definition(definition)

    def register_agentic_runtime_adapter(
        self,
        adapter: AgenticRuntimeEngineAdapter,
        *,
        definition: ProviderDefinition | None = None,
    ) -> ProviderDefinition:
        """Register an async agentic engine without requiring a process adapter."""
        active_definition = definition or self.get_provider_definition(adapter.runtime_engine_id)
        if active_definition.provider_id != adapter.runtime_engine_id:
            raise ValueError("Agentic adapter identity does not match its provider definition.")
        self._definitions[active_definition.provider_id] = active_definition
        self._agentic_runtime_adapters[active_definition.provider_id] = adapter
        return active_definition

    def list_provider_definitions(self) -> list[ProviderDefinition]:
        """Return all known provider definitions."""
        with self.native_catalog_lock:
            return [self._definitions[provider_id] for provider_id in sorted(self._definitions)]

    def get_provider_definition(self, provider_id: str) -> ProviderDefinition:
        """Return one provider definition by canonical id."""
        with self.native_catalog_lock:
            if provider_id not in self._definitions:
                raise ProviderNotFoundError(f"Provider `{provider_id}` is not registered.")
            return self._definitions[provider_id]

    def get_runtime_adapter(self, provider_id: str) -> RuntimeBackendAdapter:
        """Return the runtime backend adapter for one provider."""
        if provider_id not in self._runtime_adapters:
            raise ProviderNotFoundError(f"Runtime backend adapter `{provider_id}` is not registered.")
        return self._runtime_adapters[provider_id]

    def get_agentic_runtime_adapter(self, runtime_engine_id: str) -> AgenticRuntimeEngineAdapter:
        """Return the provider-neutral async adapter for one runtime engine."""
        if runtime_engine_id not in self._agentic_runtime_adapters:
            raise ProviderNotFoundError(
                f"Agentic runtime engine adapter `{runtime_engine_id}` is not registered."
            )
        return self._agentic_runtime_adapters[runtime_engine_id]

    def list_native_agent_installations(self) -> list["NativeAgentInstallation"]:
        """Return native registrations sorted by runtime identity."""
        return [
            self._native_agent_installations[runtime_engine_id]
            for runtime_engine_id in sorted(self._native_agent_installations)
        ]

    def get_native_agent_installation(
        self,
        runtime_engine_id: str,
    ) -> "NativeAgentInstallation":
        """Return one native registration without inferring from capabilities."""
        if runtime_engine_id not in self._native_agent_installations:
            raise ProviderNotFoundError(
                f"Native agent installation `{runtime_engine_id}` is not registered."
            )
        return self._native_agent_installations[runtime_engine_id]

    def inspect_native_agent(self, runtime_engine_id: str) -> "NativeRuntimeStatus":
        """Read redaction-safe discovery/version/health/update status on demand."""
        return self.get_native_agent_installation(runtime_engine_id).inspector.inspect()

    def get_native_agent_controller(
        self,
        runtime_engine_id: str,
    ) -> "NativeAgentRuntimeController":
        """Return the structured lifecycle facade for an executable native agent."""
        if runtime_engine_id not in self._native_agent_controllers:
            raise ProviderNotFoundError(
                f"Native agent controller `{runtime_engine_id}` is not registered."
            )
        return self._native_agent_controllers[runtime_engine_id]

    def get_subscription_usage_adapter(self, provider_id: str) -> SubscriptionUsageAdapter:
        """Return a provider adapter that implements subscription usage reads."""
        adapter = self.get_runtime_adapter(provider_id)
        reader = getattr(adapter, "read_subscription_usage", None)
        if not callable(reader):
            raise ProviderNotFoundError(f"Subscription usage adapter `{provider_id}` is not registered.")
        return adapter  # type: ignore[return-value]
