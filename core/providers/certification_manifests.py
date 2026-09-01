"""Provider suites derived from the one certified-execution TCB manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.providers.certified_execution_tcb import CERTIFIED_EXECUTION_TCB
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class CertificationStepManifest:
    step_id: str
    kind: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class CertificationSuiteManifest:
    suite_id: str
    suite_version: str
    provider_id: str
    matrix_path: str
    matrix_revision: str
    tcb_manifest_id: str
    tcb_manifest_version: str
    tcb_structure_digest: str
    artifact_paths: tuple[str, ...]
    steps: tuple[CertificationStepManifest, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)


_SHARED_FIXTURE_TESTS = (
    "tests.unit.api.test_runtime_context_capability_preflight",
    "tests.unit.api.test_runtime_message_steering",
    "tests.unit.apps.test_runtime_request_security_boundary",
    "tests.unit.providers.test_agentic_profiles",
    "tests.unit.providers.test_agentic_turn_submission",
    "tests.unit.providers.test_capability_certificate_hydration",
    "tests.unit.providers.test_capability_certificates",
    "tests.unit.providers.test_certificate_tcb_enforcement",
    "tests.unit.providers.test_certified_execution_tcb",
    "tests.unit.providers.test_certification_pipeline",
    "tests.unit.providers.test_hosted_harness_recipes",
    "tests.unit.providers.test_data_attestation_cli",
    "tests.unit.egress.test_agentic_egress",
    "tests.unit.egress.test_canonical_classification",
    "tests.unit.runtime_output_compaction.test_final_output_delivery",
    "tests.unit.runtime_output_compaction.test_runtime_integration",
    "tests.unit.runtime_state.test_effective_capabilities",
    "tests.unit.runtime_state.test_hosted_agentic_budget",
    "tests.unit.runtime_state.test_hosted_agentic_budget_accounting",
    "tests.unit.runtime_state.test_hosted_agentic_egress",
    "tests.unit.runtime_state.test_hosted_agentic_final_output_recovery",
    "tests.unit.runtime_state.test_hosted_agentic_finalization",
    "tests.unit.runtime_state.test_hosted_agentic_authority_audit",
    "tests.unit.runtime_state.test_hosted_agentic_loop",
    "tests.unit.runtime_state.test_hosted_context_loop",
    "tests.unit.runtime_state.test_hosted_context_management",
    "tests.unit.runtime_state.test_hosted_agentic_journal_loop",
    "tests.unit.runtime_state.test_hosted_agentic_multicall",
    "tests.unit.runtime_state.test_hosted_agentic_persisted_admission",
    "tests.unit.runtime_state.test_hosted_agentic_recovery",
    "tests.unit.runtime_state.test_hosted_agentic_recovery_reconciliation",
    "tests.unit.runtime_state.test_hosted_agentic_recovery_containment",
    "tests.unit.runtime_state.test_hosted_agentic_recovery_pairing",
    "tests.unit.runtime_state.test_hosted_agentic_stream_authority",
    "tests.unit.runtime_state.test_hosted_agentic_terminal_gaps",
    "tests.unit.runtime_state.test_provider_private_state",
    "tests.unit.runtime_state.test_provider_step_journal",
    "tests.unit.runtime_state.test_public_runtime_status",
    "tests.unit.runtime_state.test_remote_agentic_admission",
    "tests.unit.runtime_state.test_semantic_envelope",
    "tests.unit.runtime_state.test_semantic_envelope_governance",
    "tests.unit.runtime_state.test_runtime_api_token_recovery",
    "tests.unit.runtime_state.test_structured_runtime_failures",
    "tests.unit.recovery.test_continuation_fork",
    "tests.unit.shared.test_in_memory_collection",
    "tests.unit.shared.test_json_file_collection",
    "tests.unit.shared.test_mongo_document_collection",
    "tests.unit.runtime_tools.test_confined_filesystem",
    "tests.unit.runtime_tools.test_confined_filesystem_snapshots",
    "tests.unit.runtime_tools.test_filesystem_mutation_lineage",
    "tests.unit.runtime_tools.test_filesystem_mutation_lineage_integration",
    "tests.unit.runtime_tools.test_full_workspace_contract",
    "tests.unit.runtime_tools.test_full_workspace_instruction_scope_contract",
    "tests.unit.runtime_tools.test_full_workspace_limits_and_discovery",
    "tests.unit.runtime_tools.test_full_workspace_metadata_contract",
    "tests.unit.runtime_tools.test_full_workspace_mutation_contract",
    "tests.unit.runtime_tools.test_full_workspace_result_contract",
    "tests.unit.runtime_tools.test_full_workspace_shell_contract",
    "tests.unit.runtime_tools.test_hosted_agentic_factory_tools",
    "tests.unit.runtime_tools.test_hosted_agentic_factory_dispatch",
    "tests.unit.runtime_tools.test_hosted_agentic_lifecycle_boundaries",
    "tests.unit.runtime_tools.test_hosted_agentic_tool_execution",
    "tests.unit.runtime_tools.test_hosted_result_security_behavior",
    "tests.unit.runtime_tools.test_hosted_tool_result_admission",
    "tests.unit.runtime_tools.test_hosted_tool_result_public_authority",
    "tests.unit.runtime_tools.test_hosted_workspace_effect_admission",
    "tests.unit.runtime_tools.test_provider_input_admission",
    "tests.unit.runtime_tools.test_public_content_authority",
    "tests.unit.runtime_tools.test_tool_filesystem_listing",
    "tests.unit.runtime_tools.test_tool_orchestrator",
    "tests.unit.runtime_tools.test_tool_orchestrator_execution",
    "tests.unit.runtime_tools.test_tool_preliminary_ledger",
    "tests.unit.runtime_tools.test_tool_store",
    "tests.unit.runtime_tools.test_tool_catalog_security",
    "tests.integration.cli_mcp.test_builtin_surface_effects",
    "tests.unit.workspace.test_data_governance",
)


def _suite(
    *,
    suite_id: str,
    provider_id: str,
    matrix_path: str,
    fixture_tests: tuple[str, ...],
    live_script: str,
) -> CertificationSuiteManifest:
    return CertificationSuiteManifest(
        suite_id=suite_id,
        suite_version="31",
        provider_id=provider_id,
        matrix_path=matrix_path,
        matrix_revision=(
            "2026-09-01-r31-p4-review-closure-model-revision-tcb21"
        ),
        tcb_manifest_id=CERTIFIED_EXECUTION_TCB.manifest_id,
        tcb_manifest_version=CERTIFIED_EXECUTION_TCB.manifest_version,
        tcb_structure_digest=CERTIFIED_EXECUTION_TCB.structure_digest,
        artifact_paths=CERTIFIED_EXECUTION_TCB.artifact_paths,
        steps=(
            CertificationStepManifest(
                step_id="contract-suite",
                kind="fixture_contract",
                command=("python3", "-m", "unittest", *fixture_tests, *_SHARED_FIXTURE_TESTS),
            ),
            CertificationStepManifest(
                step_id="live-synthetic-probe",
                kind="live_probe",
                command=("python3", live_script),
            ),
        ),
    )


GOOGLE_AGENTIC_CERTIFICATION_MANIFEST = _suite(
    suite_id="maverick-google-interactions-agentic-contract",
    provider_id="google-ai-studio",
    matrix_path="docs/reference/google_agentic_certification_matrix.md",
    fixture_tests=(
        "tests.unit.providers.test_google_interactions_codec",
        "tests.unit.providers.test_google_interactions_finalization_codec",
        "tests.unit.providers.test_google_interactions_pairing_codec",
        "tests.unit.providers.test_google_interactions_journal_codec",
        "tests.unit.providers.test_google_interactions_hosted_loop",
        "tests.unit.providers.test_google_interactions_catalog",
        "tests.unit.providers.test_google_interactions_certification",
        "tests.unit.providers.test_google_agentic_profile",
        "tests.unit.providers.test_google_interactions_transport",
    ),
    live_script="scripts/run_google_interactions_probe.py",
)


OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST = _suite(
    suite_id="maverick-openrouter-agentic-contract",
    provider_id="openrouter",
    matrix_path="docs/reference/openrouter_agentic_certification_matrix.md",
    fixture_tests=(
        "tests.unit.providers.test_openrouter_agentic_codec",
        "tests.unit.providers.test_openrouter_agentic_finalization_codec",
        "tests.unit.providers.test_openrouter_agentic_pairing_codec",
        "tests.unit.providers.test_openrouter_agentic_journal_codec",
        "tests.unit.providers.test_openrouter_input_composition",
        "tests.unit.providers.test_openrouter_agentic_hosted_loop",
        "tests.unit.providers.test_openrouter_agentic_catalog",
        "tests.unit.providers.test_openrouter_agentic_mixed_stream",
        "tests.unit.providers.test_openrouter_agentic_profile",
        "tests.unit.providers.test_openrouter_agentic_transport",
        "tests.unit.scripts.test_openrouter_agentic_probe",
    ),
    live_script="scripts/run_openrouter_agentic_probe.py",
)


_MANIFESTS = {
    (item.suite_id, item.suite_version): item
    for item in (
        GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
        OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
    )
}


def get_certification_manifest(
    suite_id: str,
    suite_version: str,
) -> CertificationSuiteManifest:
    try:
        return _MANIFESTS[(suite_id, suite_version)]
    except KeyError as error:
        raise CapabilityCertificateError("certification_suite_manifest_unknown") from error


def resolve_manifest_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise CapabilityCertificateError("certification_manifest_path_invalid") from error
    return candidate
