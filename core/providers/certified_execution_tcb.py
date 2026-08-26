"""Single code-owned manifest and live digest for remote agentic execution.

The manifest is intentionally broader than an adapter.  Any code or served UI
capable of changing admission, classification, egress, tool execution, state,
or governance participates in one deterministic live digest.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat

from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class CertifiedTcbComponent:
    component_id: str
    responsibility: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CertifiedExecutionTcbManifest:
    manifest_id: str
    manifest_version: str
    components: tuple[CertifiedTcbComponent, ...]

    @property
    def structure_digest(self) -> str:
        return canonical_digest(self)

    @property
    def artifact_paths(self) -> tuple[str, ...]:
        seen: set[str] = set()
        values: list[str] = []
        for component in self.components:
            for path in component.paths:
                if path not in seen:
                    seen.add(path)
                    values.append(path)
        return tuple(values)


CERTIFIED_EXECUTION_TCB = CertifiedExecutionTcbManifest(
    manifest_id="maverick-certified-agentic-execution-tcb",
    manifest_version="1",
    components=(
        CertifiedTcbComponent(
            "data-security-boundary",
            "Workspace attestations, resource classification, taint, and egress policy.",
            (
                "core/egress",
                "core/workspaces",
                "core/shared/in_memory_collection.py",
                "core/shared/json_file_collection.py",
                "core/shared/mongo_document_collection.py",
                "core/cli/runtime_provider_commands.py",
            ),
        ),
        CertifiedTcbComponent(
            "runtime-api-admission",
            "Runtime HTTP admission, app-runtime requests, actors, and control persistence.",
            (
                "core/api",
                "core/apps",
                "core/authorization",
                "core/identity",
                "core/execution_policy",
                "core/cli/core_commands.py",
            ),
        ),
        CertifiedTcbComponent(
            "input-request-runtime",
            "Input composition, provider request building, ledger/store, lifecycle, and recovery.",
            ("core/runtime",),
        ),
        CertifiedTcbComponent(
            "tool-schema-catalog",
            "Core-owned tool schema/catalog, confinement, invocation, and result classification.",
            (
                "core/runtime/tool_catalog.py",
                "core/runtime/tool_schema.py",
                "core/runtime/tool_core_capabilities.py",
                "core/runtime/tool_filesystem_listing.py",
                "core/runtime/confined_filesystem.py",
                "core/runtime/tool_orchestrator.py",
                "core/runtime/tool_ledger.py",
                "core/runtime/tool_models.py",
                "core/cli",
                "core/mcp",
                "core/skills",
            ),
        ),
        CertifiedTcbComponent(
            "provider-codec-transport-policy",
            "Provider codecs/transports, certificate pipeline, execution binding, and live policy.",
            ("core/providers", "core/secrets"),
        ),
        CertifiedTcbComponent(
            "chat-governance",
            "Server-owned capability consumption and governance controls served by Chat.",
            (
                "apps/chat/frontend/src",
                "apps/chat/frontend/dist",
                "apps/chat/backend",
                "apps/chat/app_contract.json",
                "apps/chat/package.json",
                "apps/chat/package-lock.json",
                "apps/chat/vite.config.ts",
            ),
        ),
        CertifiedTcbComponent(
            "settings-governance",
            "Read-only posture and operator governance controls served by Settings.",
            (
                "apps/settings/frontend/src",
                "apps/settings/frontend/dist",
                "apps/settings/app_contract.json",
                "apps/settings/package.json",
                "apps/settings/package-lock.json",
                "apps/settings/vite.config.ts",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class CertifiedTcbIdentity:
    manifest_id: str
    manifest_version: str
    structure_digest: str
    live_digest: str


def certified_tcb_identity(root: Path | None = None) -> CertifiedTcbIdentity:
    """Recalculate, rather than accept, the live execution identity."""
    repository_root = root or Path(__file__).resolve().parents[2]
    return CertifiedTcbIdentity(
        manifest_id=CERTIFIED_EXECUTION_TCB.manifest_id,
        manifest_version=CERTIFIED_EXECUTION_TCB.manifest_version,
        structure_digest=CERTIFIED_EXECUTION_TCB.structure_digest,
        live_digest=compute_certified_tcb_digest(repository_root),
    )


def compute_certified_tcb_digest(root: Path) -> str:
    """Hash the manifest structure and every regular file under its path roots."""
    repository_root = root.resolve(strict=True)
    files: dict[str, Path] = {}
    for relative_root in CERTIFIED_EXECUTION_TCB.artifact_paths:
        _collect_manifest_files(repository_root, relative_root, files)
    if not files:
        raise CapabilityCertificateError("certificate_tcb_artifact_empty")
    digest = hashlib.sha256()
    digest.update(b"maverick.certified-execution-tcb.v1\x00")
    digest.update(CERTIFIED_EXECUTION_TCB.structure_digest.encode("ascii"))
    digest.update(b"\x00")
    for relative_path in sorted(files):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\x00")
        try:
            digest.update(files[relative_path].read_bytes())
        except OSError as error:
            raise CapabilityCertificateError("certificate_tcb_artifact_unavailable") from error
        digest.update(b"\x00")
    return digest.hexdigest()


def validate_remote_tcb_identity(
    *,
    manifest_id: str,
    manifest_version: str,
    structure_digest: str,
    live_digest: str,
    root: Path | None = None,
) -> CertifiedTcbIdentity:
    """Require an exact current TCB identity for any hosted remote authority."""
    if not all((manifest_id, manifest_version, structure_digest, live_digest)):
        raise CapabilityCertificateError("certificate_tcb_identity_missing")
    current = certified_tcb_identity(root)
    if (
        manifest_id != current.manifest_id
        or manifest_version != current.manifest_version
        or structure_digest != current.structure_digest
    ):
        raise CapabilityCertificateError("certificate_tcb_identity_mismatch")
    if live_digest != current.live_digest:
        raise CapabilityCertificateError("certificate_tcb_drift")
    return current


def is_certified_tcb_component(component_id: str) -> bool:
    return any(
        component.component_id == component_id
        for component in CERTIFIED_EXECUTION_TCB.components
    )


def is_exact_codex_identity(
    *,
    runtime_engine_id: str,
    adapter_id: str,
    model_provider_id: str,
    provider_protocol: str,
) -> bool:
    """Keep the local Codex contract outside hosted-remote TCB classification."""
    return (
        runtime_engine_id == "codex"
        and adapter_id == "codex-app-server"
        and model_provider_id == "codex"
        and provider_protocol == "codex-app-server-stdio"
    )


def tcb_public_projection(
    *,
    expected_live_digest: str,
    root: Path | None = None,
) -> dict[str, object]:
    """Return posture without paths, source content, or credential authority."""
    current = certified_tcb_identity(root)
    return {
        "manifest_id": current.manifest_id,
        "manifest_version": current.manifest_version,
        "structure_digest": current.structure_digest,
        "expected_live_digest": expected_live_digest or None,
        "live_digest": current.live_digest,
        "posture": (
            "active" if expected_live_digest == current.live_digest else "drifted"
        ),
    }


def _collect_manifest_files(
    repository_root: Path,
    relative_root: str,
    files: dict[str, Path],
) -> None:
    if (
        not relative_root
        or relative_root.startswith("/")
        or ".." in Path(relative_root).parts
        or "\x00" in relative_root
    ):
        raise CapabilityCertificateError("certificate_tcb_manifest_path_invalid")
    candidate = repository_root / relative_root
    try:
        candidate.relative_to(repository_root)
        metadata = candidate.lstat()
    except (OSError, ValueError) as error:
        raise CapabilityCertificateError("certificate_tcb_artifact_missing") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise CapabilityCertificateError("certificate_tcb_artifact_symlink")
    if stat.S_ISREG(metadata.st_mode):
        files[candidate.relative_to(repository_root).as_posix()] = candidate
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise CapabilityCertificateError("certificate_tcb_artifact_invalid")
    for directory, directory_names, file_names in os.walk(candidate, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in {"__pycache__", "node_modules", ".git"}
        )
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise CapabilityCertificateError("certificate_tcb_artifact_symlink")
        for name in sorted(file_names):
            path = directory_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise CapabilityCertificateError("certificate_tcb_artifact_symlink")
            if not stat.S_ISREG(metadata.st_mode) or name.endswith((".pyc", ".pyo")):
                continue
            relative = path.relative_to(repository_root).as_posix()
            files[relative] = path
