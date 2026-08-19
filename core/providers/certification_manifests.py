"""Versioned, code-owned manifests for remote agentic certification suites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    artifact_paths: tuple[str, ...]
    steps: tuple[CertificationStepManifest, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)


GOOGLE_AGENTIC_CERTIFICATION_MANIFEST = CertificationSuiteManifest(
    suite_id="maverick-google-interactions-agentic-contract",
    suite_version="5",
    provider_id="google-ai-studio",
    matrix_path="docs/reference/google_agentic_certification_matrix.md",
    matrix_revision="2026-08-19-r4",
    artifact_paths=(
        "core/providers/agentic_models.py",
        "core/providers/capability_models.py",
        "core/providers/google_agentic_profile.py",
        "core/providers/google_interactions_client.py",
        "core/providers/google_interactions_models.py",
        "core/providers/google_interactions_request.py",
        "core/providers/google_interactions_stream.py",
        "core/providers/google_interactions_state.py",
        "core/providers/google_interactions_transport.py",
        "core/providers/google_interactions_probe.py",
        "core/providers/google_agentic_certification.py",
        "core/providers/certification_pipeline.py",
        "core/providers/store.py",
        "core/runtime/agentic_execution.py",
        "core/runtime/authority.py",
        "core/runtime/authority_service.py",
        "core/runtime/execution.py",
        "core/runtime/execution_binding.py",
        "core/runtime/failure_messages.py",
        "core/runtime/hosted_agentic_engine.py",
        "core/runtime/hosted_agentic_factory.py",
        "core/runtime/hosted_agentic_loop.py",
        "core/runtime/hosted_agentic_policy.py",
        "core/runtime/hosted_agentic_request.py",
        "core/runtime/hosted_agentic_stream.py",
        "core/runtime/tool_catalog.py",
        "core/runtime/tool_core_capabilities.py",
        "core/runtime/tool_filesystem_listing.py",
        "core/runtime/turn_submission_service_events.py",
        "core/runtime/turn_submission_service_failures.py",
        "core/runtime/turn_submission_service_output.py",
        "core/runtime/turn_submission_service_runtime.py",
        "core/runtime/turn_submission_service_submit.py",
        "apps/chat/frontend/src/lib/providerRuntimeOptions.ts",
        "apps/chat/frontend/src/lib/transcript.ts",
        "scripts/run_google_interactions_probe.py",
        "tests/unit/providers/test_google_interactions_codec.py",
        "tests/unit/providers/test_google_interactions_certification.py",
        "tests/unit/providers/test_google_interactions_transport.py",
        "tests/unit/runtime_state/test_hosted_agentic_authority_audit.py",
        "tests/unit/runtime_state/test_hosted_agentic_loop.py",
        "tests/unit/runtime_state/test_structured_runtime_failures.py",
        "tests/unit/runtime_tools/test_tool_filesystem_listing.py",
        "tests/unit/runtime_tools/test_tool_orchestrator.py",
    ),
    steps=(
        CertificationStepManifest(
            step_id="contract-suite",
            kind="fixture_contract",
            command=(
                "python3", "-m", "unittest",
                "tests.unit.providers.test_google_interactions_codec",
                "tests.unit.providers.test_google_interactions_certification",
                "tests.unit.providers.test_google_interactions_transport",
                "tests.unit.runtime_state.test_hosted_agentic_authority_audit",
                "tests.unit.runtime_state.test_hosted_agentic_loop",
                "tests.unit.runtime_state.test_structured_runtime_failures",
                "tests.unit.runtime_tools.test_tool_filesystem_listing",
                "tests.unit.runtime_tools.test_tool_orchestrator",
            ),
        ),
        CertificationStepManifest(
            step_id="live-synthetic-probe",
            kind="live_probe",
            command=("python3", "scripts/run_google_interactions_probe.py"),
        ),
    ),
)


OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST = CertificationSuiteManifest(
    suite_id="maverick-openrouter-agentic-contract",
    suite_version="5",
    provider_id="openrouter",
    matrix_path="docs/reference/openrouter_agentic_certification_matrix.md",
    matrix_revision="2026-08-19-r4",
    artifact_paths=(
        "core/providers/agentic_models.py",
        "core/providers/capability_models.py",
        "core/providers/openrouter_agentic_profile.py",
        "core/providers/openrouter_agentic_client.py",
        "core/providers/openrouter_agentic_request.py",
        "core/providers/openrouter_agentic_models.py",
        "core/providers/openrouter_agentic_state.py",
        "core/providers/openrouter_agentic_stream.py",
        "core/providers/openrouter_agentic_stream_fields.py",
        "core/providers/openrouter_agentic_transport.py",
        "core/providers/openrouter_agentic_certification.py",
        "core/providers/certification_pipeline.py",
        "core/providers/store.py",
        "core/runtime/agentic_execution.py",
        "core/runtime/authority.py",
        "core/runtime/authority_service.py",
        "core/runtime/execution.py",
        "core/runtime/execution_binding.py",
        "core/runtime/failure_messages.py",
        "core/runtime/hosted_agentic_engine.py",
        "core/runtime/hosted_agentic_factory.py",
        "core/runtime/hosted_agentic_loop.py",
        "core/runtime/hosted_agentic_policy.py",
        "core/runtime/hosted_agentic_request.py",
        "core/runtime/hosted_agentic_stream.py",
        "core/runtime/tool_catalog.py",
        "core/runtime/tool_core_capabilities.py",
        "core/runtime/tool_filesystem_listing.py",
        "core/runtime/turn_submission_service_events.py",
        "core/runtime/turn_submission_service_failures.py",
        "core/runtime/turn_submission_service_output.py",
        "core/runtime/turn_submission_service_runtime.py",
        "core/runtime/turn_submission_service_submit.py",
        "apps/chat/frontend/src/lib/providerRuntimeOptions.ts",
        "apps/chat/frontend/src/lib/transcript.ts",
        "scripts/run_openrouter_agentic_probe.py",
        "tests/unit/providers/test_openrouter_agentic_codec.py",
        "tests/unit/providers/test_openrouter_agentic_mixed_stream.py",
        "tests/unit/providers/test_openrouter_agentic_transport.py",
        "tests/unit/runtime_state/test_hosted_agentic_authority_audit.py",
        "tests/unit/runtime_state/test_hosted_agentic_loop.py",
        "tests/unit/runtime_state/test_structured_runtime_failures.py",
        "tests/unit/runtime_tools/test_tool_filesystem_listing.py",
        "tests/unit/runtime_tools/test_tool_orchestrator.py",
        "tests/unit/scripts/test_openrouter_agentic_probe.py",
    ),
    steps=(
        CertificationStepManifest(
            step_id="contract-suite",
            kind="fixture_contract",
            command=(
                "python3", "-m", "unittest",
                "tests.unit.providers.test_openrouter_agentic_codec",
                "tests.unit.providers.test_openrouter_agentic_mixed_stream",
                "tests.unit.providers.test_openrouter_agentic_transport",
                "tests.unit.runtime_state.test_hosted_agentic_authority_audit",
                "tests.unit.runtime_state.test_hosted_agentic_loop",
                "tests.unit.runtime_state.test_structured_runtime_failures",
                "tests.unit.runtime_tools.test_tool_filesystem_listing",
                "tests.unit.runtime_tools.test_tool_orchestrator",
                "tests.unit.scripts.test_openrouter_agentic_probe",
            ),
        ),
        CertificationStepManifest(
            step_id="live-synthetic-probe",
            kind="live_probe",
            command=("python3", "scripts/run_openrouter_agentic_probe.py"),
        ),
    ),
)

_MANIFESTS = {
    (item.suite_id, item.suite_version): item
    for item in (
        GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
        OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
    )
}


def get_certification_manifest(suite_id: str, suite_version: str) -> CertificationSuiteManifest:
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
