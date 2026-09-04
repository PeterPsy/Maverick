"""Builtin native-agent registrations; only Codex is release eligible."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shlex
import shutil
import subprocess

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
    NativeAgentModelSelection,
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
        availability, executable_path = self.discover()
        runtime_version = self.version() if availability == "installed" else None
        health, reason_codes = self.health()
        update_status, update_detail = self.update_status()
        return NativeRuntimeStatus(
            availability=availability,
            executable_path=executable_path,
            runtime_version=runtime_version,
            health=health,
            reason_codes=reason_codes,
            update_status=update_status,
            update_detail=update_detail,
        )


def build_codex_native_installation(adapter) -> NativeAgentInstallation:
    """Describe the existing Codex app-server integration without changing it."""
    definition = adapter.provider_definition()
    recipe_payload = {
        "recipe_id": "codex-native-app-server",
        "revision": NATIVE_AGENT_RECIPE_REVISION,
        "protocol": "codex-app-server-stdio",
        "context_owner": "native_runtime",
        "prompt_contract_revision": "codex-native-prompt-v1",
    }
    selections = tuple(
        NativeAgentModelSelection(
            model_provider_id="codex",
            model_id=option.model_id,
            model_revision=None,
            revision_policy="provider_alias",
        )
        for option in definition.model_options
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
        model_selections=selections,
        effects=NativeAgentEffectContract(
            mode="mapped_hybrid",
            workspace_confined=True,
            process_tree_supervised=True,
            structured_effect_events=True,
            approval_policy="maverick_common_approval_policy",
            sandbox_policy_revision=NATIVE_AGENT_SANDBOX_POLICY_REVISION,
        ),
        certificate=NativeAgentCertificateReference(
            certification_state="legacy_certified",
            certificate_id_template="capability-certificate:{profile_id}:{profile_revision}",
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
        model_selections=(
            NativeAgentModelSelection(
                model_provider_id="google",
                model_id="provider-default",
                model_revision=None,
                revision_policy="provider_alias",
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
            certification_state="candidate",
            certificate_id_template=None,
            full_workspace_contract_revision=None,
        ),
        inspector=CommandNativeRuntimeInspector("gemini"),
    )
