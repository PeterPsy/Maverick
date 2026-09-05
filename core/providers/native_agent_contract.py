"""Install-time contract for structured native coding-agent integrations."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol

from core.providers.execution_families import NATIVE_AGENT_EXECUTION_FAMILY
from core.providers.native_runtime_artifact import NativeRuntimeArtifact


NativeProtocolKind = Literal[
    "app_server",
    "sdk",
    "api",
    "json_rpc",
    "jsonl",
    "structured_cli",
]
NativeEffectMode = Literal[
    "maverick_tools",
    "sandboxed_native_tools",
    "mapped_hybrid",
]
NativeAvailability = Literal["installed", "not_installed", "unknown"]
NativeHealthState = Literal["healthy", "degraded", "unavailable", "unknown"]
NativeUpdateState = Literal["current", "update_available", "unknown"]

REQUIRED_NATIVE_OPERATIONS = frozenset(
    {
        "discover",
        "version",
        "health",
        "update_status",
        "launch",
        "connect",
        "resume",
        "start_turn",
        "stream_events",
        "final_output",
        "steer",
        "interrupt",
        "recover",
        "cleanup",
        "close",
    }
)
_NATIVE_OPERATION_ADAPTER_METHODS = {
    "launch": "build_launch_spec",
    "start_turn": "execute_turn",
    "steer": "steer_turn",
    "interrupt": "interrupt_turn",
    "recover": "prewarm_runtime",
    "cleanup": "close_runtime",
    "close": "close_runtime",
}
_REQUIRED_NATIVE_RUNTIME_ADAPTER_METHODS = (
    "provider_definition",
    "validate_backend",
    "prepare_runtime_skills",
)
REQUIRED_NATIVE_INSPECTOR_METHODS = (
    "discover",
    "version",
    "health",
    "update_status",
    "inspect",
)
_STRUCTURED_PROTOCOLS = frozenset(
    {"app_server", "sdk", "api", "json_rpc", "jsonl", "structured_cli"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class NativeAgentAdapterManifest:
    """Trusted integration identity, protocol, and lifecycle declaration."""

    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    protocol_kind: NativeProtocolKind
    protocol_id: str
    protocol_version: str | None
    structured_event_schema: str
    lifecycle_operations: tuple[str, ...]
    machine_readable: bool
    human_terminal_scraping: bool
    trusted_distribution: str


@dataclass(frozen=True)
class NativeAgentHarnessRecipe:
    """Immutable native-agent harness configuration, separate from the adapter."""

    recipe_id: str
    revision: str
    digest: str
    prompt_contract_revision: str
    context_owner: Literal["native_runtime", "maverick"]


@dataclass(frozen=True)
class NativeAgentModelProviderConnection:
    """One runtime-to-model-provider connection covered by the integration."""

    model_provider_id: str
    catalog_provider_id: str


@dataclass(frozen=True)
class NativeAgentEffectContract:
    """How native tool effects remain confined and observable."""

    mode: NativeEffectMode
    workspace_confined: bool
    process_tree_supervised: bool
    structured_effect_events: bool
    approval_policy: str
    sandbox_policy_revision: str


@dataclass(frozen=True)
class NativeAgentCertificateReference:
    """Connection certificate kept separate from adapter and recipe identities."""

    connection_certificate_ids: tuple[tuple[str, str], ...]
    full_workspace_contract_revision: str | None


@dataclass(frozen=True)
class NativeRuntimeStatus:
    """Redaction-safe install, version, health, and update observation."""

    availability: NativeAvailability
    executable_path: str | None
    runtime_version: str | None
    health: NativeHealthState
    reason_codes: tuple[str, ...]
    update_status: NativeUpdateState
    update_detail: str | None = None


class NativeRuntimeInspector(Protocol):
    """Side-effect-free inspection boundary for one local native runtime."""

    def discover(self) -> tuple[NativeAvailability, str | None]: ...

    def version(self) -> str | None: ...

    def health(self) -> tuple[NativeHealthState, tuple[str, ...]]: ...

    def update_status(self) -> tuple[NativeUpdateState, str | None]: ...

    def inspect(self) -> NativeRuntimeStatus: ...


@dataclass(frozen=True)
class NativeAgentInstallation:
    """Complete install-time registration assembled from separate trust domains."""

    manifest: NativeAgentAdapterManifest
    recipe: NativeAgentHarnessRecipe
    model_provider_connections: tuple[NativeAgentModelProviderConnection, ...]
    effects: NativeAgentEffectContract
    certificate: NativeAgentCertificateReference
    inspector: NativeRuntimeInspector
    runtime_artifact: NativeRuntimeArtifact | None = None

    @property
    def execution_family(self) -> str:
        return NATIVE_AGENT_EXECUTION_FAMILY

    @property
    def certification_configured(self) -> bool:
        """A reference permits wiring, not release: live store validation grants it."""
        return bool(self.certificate.connection_certificate_ids)


def validate_native_agent_installation(installation: NativeAgentInstallation) -> None:
    """Fail closed on unstructured lifecycle or unobservable native effects."""
    manifest = installation.manifest
    if not all(
        callable(getattr(installation.inspector, method_name, None))
        for method_name in REQUIRED_NATIVE_INSPECTOR_METHODS
    ):
        raise ValueError("native_agent_inspector_incomplete")
    if manifest.protocol_kind not in _STRUCTURED_PROTOCOLS:
        raise ValueError("native_agent_protocol_unstructured")
    if not manifest.machine_readable or manifest.human_terminal_scraping:
        raise ValueError("native_agent_terminal_scraping_forbidden")
    operations = frozenset(manifest.lifecycle_operations)
    if len(operations) != len(manifest.lifecycle_operations):
        raise ValueError("native_agent_lifecycle_operation_duplicate")
    if not REQUIRED_NATIVE_OPERATIONS.issubset(operations):
        raise ValueError("native_agent_lifecycle_incomplete")
    if not manifest.structured_event_schema.strip():
        raise ValueError("native_agent_event_schema_missing")
    if not installation.effects.workspace_confined:
        raise ValueError("native_agent_effects_unconfined")
    if not installation.effects.process_tree_supervised:
        raise ValueError("native_agent_process_unsupervised")
    if not installation.effects.structured_effect_events:
        raise ValueError("native_agent_effects_unobserved")
    if not installation.effects.sandbox_policy_revision.strip():
        raise ValueError("native_agent_sandbox_policy_missing")
    if not _SHA256.fullmatch(installation.recipe.digest):
        raise ValueError("native_agent_recipe_digest_invalid")
    if not installation.model_provider_connections:
        raise ValueError("native_agent_model_provider_connection_missing")
    connection_ids: set[str] = set()
    catalog_ids: set[str] = set()
    for connection in installation.model_provider_connections:
        identity = (
            connection.model_provider_id.strip(),
            connection.catalog_provider_id.strip(),
        )
        if not all(identity) or identity != (
            connection.model_provider_id,
            connection.catalog_provider_id,
        ):
            raise ValueError("native_agent_model_provider_connection_invalid")
        if identity[0] in connection_ids or identity[1] in catalog_ids:
            raise ValueError("native_agent_model_provider_connection_duplicate")
        connection_ids.add(identity[0])
        catalog_ids.add(identity[1])
    certificate = installation.certificate
    if installation.certification_configured and (
        not certificate.full_workspace_contract_revision
        or {item[0] for item in certificate.connection_certificate_ids} != connection_ids
        or len(certificate.connection_certificate_ids) != len(connection_ids)
        or any(not item[1].strip() for item in certificate.connection_certificate_ids)
    ):
        raise ValueError("native_agent_certificate_contract_incomplete")


def validate_native_runtime_adapter(
    installation: NativeAgentInstallation,
    adapter: object,
) -> None:
    """Require executable methods behind every certified native lifecycle."""
    required_methods = {
        *_REQUIRED_NATIVE_RUNTIME_ADAPTER_METHODS,
        *(
            method_name
            for operation, method_name in _NATIVE_OPERATION_ADAPTER_METHODS.items()
            if operation in installation.manifest.lifecycle_operations
        ),
    }
    missing = tuple(
        method_name
        for method_name in sorted(required_methods)
        if not callable(getattr(adapter, method_name, None))
    )
    if missing:
        raise ValueError("native_agent_runtime_adapter_incomplete")
