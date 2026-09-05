"""Builtin native-agent registrations; only Codex is release eligible."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shlex
import shutil
import subprocess
from threading import Lock
from time import monotonic

from core.providers.models import (
    ProviderCapabilitySet,
    ProviderDefinition,
    ProviderModelOption,
)
from core.providers.native_agent_contract import (
    REQUIRED_NATIVE_OPERATIONS,
    NativeAgentAdapterManifest,
    NativeAgentCertificateReference,
    NativeAgentEffectContract,
    NativeAgentHarnessRecipe,
    NativeAgentInstallation,
    NativeAgentModelProviderConnection,
    NativeAvailability,
    NativeHealthState,
    NativeRuntimeStatus,
    NativeUpdateState,
)
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import FULL_WORKSPACE_CONTRACT_REVISION


NATIVE_AGENT_RECIPE_REVISION = "1"
NATIVE_AGENT_SANDBOX_POLICY_REVISION = "maverick-native-sandbox-v1"
GEMINI_CLI_CANDIDATE_PROVIDER_ID = "gemini-cli"
_INSPECTION_CACHE_SECONDS = 5.0
_INSPECTION_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, NativeRuntimeStatus]] = {}
_INSPECTION_CACHE_LOCK = Lock()


class CommandNativeRuntimeInspector:
    """Bounded, non-interactive local binary inspection with no update action."""

    def __init__(
        self,
        command: str,
        *,
        version_args: tuple[str, ...] = ("--version",),
        timeout_seconds: float = 2.0,
    ) -> None:
        self._command = command
        self._version_args = version_args
        self._timeout_seconds = timeout_seconds

    def discover(self) -> tuple[NativeAvailability, str | None]:
        argv = shlex.split(self._command)
        if not argv:
            return "not_installed", None
        candidate = Path(argv[0]).expanduser()
        resolved = str(candidate.resolve()) if candidate.exists() else shutil.which(argv[0])
        if not resolved:
            return "not_installed", None
        return "installed", resolved

    def version(self) -> str | None:
        availability, executable_path = self.discover()
        if availability != "installed" or executable_path is None:
            return None
        argv = [executable_path, *shlex.split(self._command)[1:], *self._version_args]
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        first_line = (completed.stdout or completed.stderr).strip().splitlines()
        return first_line[0][:256] if first_line else None

    def health(self) -> tuple[NativeHealthState, tuple[str, ...]]:
        availability, _path = self.discover()
        if availability != "installed":
            return "unavailable", ("runtime_not_installed",)
        if self.version() is None:
            return "degraded", ("runtime_version_unavailable",)
        return "healthy", ()

    def update_status(self) -> tuple[NativeUpdateState, str | None]:
        # Update channels are runtime/distribution specific. Never infer one
        # from an installed version or perform network I/O during status reads.
        return "unknown", "No trusted offline update channel is configured."

    def inspect(self) -> NativeRuntimeStatus:
        cache_key = (self._command, self._version_args)
        with _INSPECTION_CACHE_LOCK:
            cached = _INSPECTION_CACHE.get(cache_key)
            if cached is not None and monotonic() - cached[0] < _INSPECTION_CACHE_SECONDS:
                return cached[1]
        availability, executable_path = self.discover()
        runtime_version = self.version() if availability == "installed" else None
        if availability != "installed":
            health, reason_codes = "unavailable", ("runtime_not_installed",)
        elif runtime_version is None:
            health, reason_codes = "degraded", ("runtime_version_unavailable",)
        else:
            health, reason_codes = "healthy", ()
        update_status, update_detail = self.update_status()
        result = NativeRuntimeStatus(
            availability=availability,
            executable_path=executable_path,
            runtime_version=runtime_version,
            health=health,
            reason_codes=reason_codes,
            update_status=update_status,
            update_detail=update_detail,
        )
        with _INSPECTION_CACHE_LOCK:
            _INSPECTION_CACHE[cache_key] = (monotonic(), result)
        return result


def build_codex_native_installation(adapter) -> NativeAgentInstallation:
    """Describe the certified Codex app-server integration and its connection."""
    from core.providers.agentic_profiles import CODEX_PROFILE_REVISION

    recipe_payload = {
        "recipe_id": "codex-native-app-server",
        "revision": NATIVE_AGENT_RECIPE_REVISION,
        "protocol": "codex-app-server-stdio",
        "context_owner": "native_runtime",
        "prompt_contract_revision": "codex-native-prompt-v1",
    }
    connections = (
        NativeAgentModelProviderConnection(
            model_provider_id="codex",
            catalog_provider_id="codex",
        ),
    )
    return NativeAgentInstallation(
        manifest=NativeAgentAdapterManifest(
            runtime_engine_id="codex",
            adapter_id=str(adapter.adapter_id),
            adapter_version=str(adapter.adapter_version),
            protocol_kind="app_server",
            protocol_id="codex-app-server-stdio",
            protocol_version=None,
            structured_event_schema="maverick.runtime-provider-event.v1",
            lifecycle_operations=tuple(sorted(REQUIRED_NATIVE_OPERATIONS)),
            machine_readable=True,
            human_terminal_scraping=False,
            trusted_distribution="maverick_builtin",
        ),
        recipe=NativeAgentHarnessRecipe(
            recipe_id=str(recipe_payload["recipe_id"]),
            revision=NATIVE_AGENT_RECIPE_REVISION,
            digest=canonical_digest(recipe_payload),
            prompt_contract_revision=str(recipe_payload["prompt_contract_revision"]),
            context_owner="native_runtime",
        ),
        model_provider_connections=connections,
        effects=NativeAgentEffectContract(
            mode="mapped_hybrid",
            workspace_confined=True,
            process_tree_supervised=True,
            structured_effect_events=True,
            approval_policy="maverick_common_approval_policy",
            sandbox_policy_revision=NATIVE_AGENT_SANDBOX_POLICY_REVISION,
        ),
        certificate=NativeAgentCertificateReference(
            connection_certificate_ids=(("codex", f"native-connection:codex:codex:{CODEX_PROFILE_REVISION}"),),
            full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        ),
        inspector=CommandNativeRuntimeInspector(adapter.codex_command),
    )


def build_gemini_cli_candidate_definition(
    now: datetime | None = None,
) -> ProviderDefinition:
    """Publish a discovery-only second native adapter; execution stays disabled."""
    timestamp = now or datetime.now(tz=UTC)
    return ProviderDefinition(
        provider_id=GEMINI_CLI_CANDIDATE_PROVIDER_ID,
        label="Gemini CLI",
        description=(
            "Discovery-only native-agent candidate. Execution remains disabled "
            "until an exact adapter, recipe, model, and certificate are approved."
        ),
        kind="runtime_backend",
        provider_role="runtime_engine",
        status="disabled",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=False,
            supports_streaming=False,
            supports_tools=False,
            supports_mcp=False,
            supports_skills=False,
            supports_filesystem_access=False,
            supports_remote_execution=False,
            supports_api_key_auth=False,
            supports_local_binary=True,
            input_modalities=["text"],
            output_modalities=["text", "events"],
        ),
        default_model_family="provider-default",
        requires_credentials=False,
        supported_execution_modes=["sandbox"],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=[
            ProviderModelOption(
                model_id="provider-default",
                label="Provider default (unverified)",
                description="Candidate alias; no agentic authority is granted.",
                default_reasoning_effort=None,
            )
        ],
    )


def build_gemini_cli_candidate_installation() -> NativeAgentInstallation:
    """Return a complete but deliberately uncertified native registration."""
    recipe_payload = {
        "recipe_id": "gemini-cli-native-candidate",
        "revision": NATIVE_AGENT_RECIPE_REVISION,
        "protocol": "structured-cli-unverified",
        "context_owner": "native_runtime",
        "prompt_contract_revision": "candidate",
    }
    return NativeAgentInstallation(
        manifest=NativeAgentAdapterManifest(
            runtime_engine_id=GEMINI_CLI_CANDIDATE_PROVIDER_ID,
            adapter_id="gemini-cli-structured-candidate",
            adapter_version="0",
            protocol_kind="structured_cli",
            protocol_id="gemini-cli-structured-candidate",
            protocol_version=None,
            structured_event_schema="candidate.unverified",
            lifecycle_operations=tuple(sorted(REQUIRED_NATIVE_OPERATIONS)),
            machine_readable=True,
            human_terminal_scraping=False,
            trusted_distribution="maverick_candidate_manifest",
        ),
        recipe=NativeAgentHarnessRecipe(
            recipe_id=str(recipe_payload["recipe_id"]),
            revision=NATIVE_AGENT_RECIPE_REVISION,
            digest=canonical_digest(recipe_payload),
            prompt_contract_revision="candidate",
            context_owner="native_runtime",
        ),
        model_provider_connections=(
            NativeAgentModelProviderConnection(
                model_provider_id="google",
                catalog_provider_id=GEMINI_CLI_CANDIDATE_PROVIDER_ID,
            ),
        ),
        effects=NativeAgentEffectContract(
            mode="sandboxed_native_tools",
            workspace_confined=True,
            process_tree_supervised=True,
            structured_effect_events=True,
            approval_policy="maverick_common_approval_policy",
            sandbox_policy_revision=NATIVE_AGENT_SANDBOX_POLICY_REVISION,
        ),
        certificate=NativeAgentCertificateReference(
            connection_certificate_ids=(),
            full_workspace_contract_revision=None,
        ),
        inspector=CommandNativeRuntimeInspector("gemini"),
    )
