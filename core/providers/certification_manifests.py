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
    suite_version="3",
    provider_id="google-ai-studio",
    matrix_path="docs/reference/google_agentic_certification_matrix.md",
    matrix_revision="2026-08-16-r2",
    artifact_paths=(
        "core/providers/google_interactions_client.py",
        "core/providers/google_interactions_request.py",
        "core/providers/google_interactions_stream.py",
        "core/providers/google_interactions_state.py",
        "core/providers/google_interactions_transport.py",
        "core/providers/google_interactions_probe.py",
        "core/providers/google_agentic_certification.py",
        "core/providers/certification_pipeline.py",
        "scripts/run_google_interactions_probe.py",
        "tests/unit/providers/test_google_interactions_codec.py",
    ),
    steps=(
        CertificationStepManifest(
            step_id="contract-suite",
            kind="fixture_contract",
            command=(
                "python3", "-m", "unittest",
                "tests.unit.providers.test_google_interactions_codec",
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
    suite_version="3",
    provider_id="openrouter",
    matrix_path="docs/reference/openrouter_agentic_certification_matrix.md",
    matrix_revision="2026-08-17-r2",
    artifact_paths=(
        "core/providers/openrouter_agentic_client.py",
        "core/providers/openrouter_agentic_request.py",
        "core/providers/openrouter_agentic_stream.py",
        "core/providers/openrouter_agentic_transport.py",
        "core/providers/openrouter_agentic_certification.py",
        "core/providers/certification_pipeline.py",
        "scripts/run_openrouter_agentic_probe.py",
        "tests/unit/providers/test_openrouter_agentic_codec.py",
        "tests/unit/providers/test_openrouter_agentic_transport.py",
    ),
    steps=(
        CertificationStepManifest(
            step_id="contract-suite",
            kind="fixture_contract",
            command=(
                "python3", "-m", "unittest",
                "tests.unit.providers.test_openrouter_agentic_codec",
                "tests.unit.providers.test_openrouter_agentic_transport",
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
