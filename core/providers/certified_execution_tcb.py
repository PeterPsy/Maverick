"""Single code-owned manifest and live digest for remote agentic execution.

The manifest is intentionally broader than an adapter.  Any code or served UI
capable of changing admission, classification, egress, tool execution, state,
or governance participates in one deterministic live digest.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import struct
from threading import RLock

from core.providers.certified_tcb_dependencies import (
    CertifiedTcbDependencyContract,
    CertifiedTcbDependencyReport,
    audit_certified_tcb_dependencies as _audit_certified_tcb_dependencies,
)
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_builtin_app_execution import (
    certified_hosted_builtin_app_artifact_paths,
)


_DEPENDENCY_AUDIT_CACHE_LIMIT = 16
_DEPENDENCY_AUDIT_CACHE: OrderedDict[tuple[str, str, str], None] = OrderedDict()
_DEPENDENCY_AUDIT_CACHE_LOCK = RLock()
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_HOSTED_BUILTIN_APP_ARTIFACT_PATHS = (
    certified_hosted_builtin_app_artifact_paths(
        apps_root=_REPOSITORY_ROOT / "apps",
    )
)


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
    dependency_contracts: tuple[CertifiedTcbDependencyContract, ...]

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
    manifest_version="31",
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
            "transitive-execution-dependencies",
            "Audited package, orchestration, recovery, audit, usage, and app-entrypoint callouts.",
            (
                "core/__init__.py",
                "core/app_sdk/__init__.py",
                "core/app_sdk/display_models.py",
                "core/app_sdk/errors.py",
                "core/app_sdk/storage.py",
                "core/inter_agent/__init__.py",
                "core/inter_agent/errors.py",
                "core/inter_agent/events.py",
                "core/inter_agent/generalist_context.py",
                "core/inter_agent/models.py",
                "core/inter_agent/orchestration_participants.py",
                "core/inter_agent/orchestration_plan.py",
                "core/inter_agent/orchestration_planner_catalog.py",
                "core/inter_agent/orchestration_planner_catalog_search.py",
                "core/inter_agent/orchestration_prompts.py",
                "core/inter_agent/orchestration_runtime.py",
                "core/inter_agent/orchestration_state.py",
                "core/inter_agent/orchestration_tasks.py",
                "core/inter_agent/orchestration_topology.py",
                "core/inter_agent/service.py",
                "core/inter_agent/store.py",
                "core/observability",
                "core/recovery",
                "core/shared/__init__.py",
                "core/shared/entrypoints.py",
                "core/shared/repository.py",
                "core/shared/tool_effects.py",
                "core/usage",
            ),
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
                "core/runtime/confined_filesystem_batch.py",
                "core/runtime/confined_filesystem_metadata.py",
                "core/runtime/confined_filesystem_delete.py",
                "core/runtime/confined_filesystem_mutation_support.py",
                "core/runtime/confined_filesystem_mutations.py",
                "core/runtime/confined_filesystem_search.py",
                "core/runtime/filesystem_mutation_lineage.py",
                "core/runtime/full_workspace_contract.py",
                "core/runtime/hosted_behavior_probe_cache.py",
                "core/runtime/hosted_filesystem_result_behavior.py",
                "core/runtime/hosted_result_authority_guard.py",
                "core/runtime/hosted_result_security_behavior.py",
                "core/runtime/hosted_shell_process_behavior.py",
                "core/runtime/hosted_shell_process_behavior_support.py",
                "core/runtime/hosted_tool_security_probes.py",
                "core/runtime/hosted_transport_security_probe.py",
                "core/runtime/hosted_transport_security_probe_support.py",
                "core/runtime/hosted_workspace_effect_security_probe.py",
                "core/runtime/hosted_process_output.py",
                "core/runtime/hosted_tool_process_registry.py",
                "core/runtime/hosted_workspace_effect_support.py",
                "core/runtime/hosted_workspace_effects.py",
                "core/runtime/hosted_workspace_shell.py",
                "core/runtime/tool_discovery_capabilities.py",
                "core/runtime/tool_discovery_authority.py",
                "core/runtime/tool_discovery_support.py",
                "core/runtime/tool_full_workspace_capabilities.py",
                "core/runtime/tool_full_workspace_schemas.py",
                "core/runtime/tool_full_workspace_support.py",
                "core/runtime/tool_process_capabilities.py",
                "core/runtime/tool_result_artifacts.py",
                "core/runtime/tool_result_classification.py",
                "core/runtime/tool_orchestrator.py",
                "core/runtime/tool_ledger.py",
                "core/runtime/tool_models.py",
                "core/cli",
                "core/mcp",
                "core/skills",
            ),
        ),
        CertifiedTcbComponent(
            "hosted-built-in-app-execution",
            "Exact entrypoint and app-local executable closure admitted for hosted reads.",
            _HOSTED_BUILTIN_APP_ARTIFACT_PATHS,
        ),
        CertifiedTcbComponent(
            "provider-codec-transport-policy",
            "Provider codecs/transports, certificate pipeline, execution binding, and live policy.",
            (
                "core/providers",
                "core/secrets",
                "scripts/run_agentic_certification.py",
                "scripts/run_google_interactions_probe.py",
                "scripts/run_openrouter_agentic_probe.py",
            ),
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
    dependency_contracts=(
        CertifiedTcbDependencyContract(
            "runtime-admission",
            "Session/turn admission, app-runtime admission, continuation, and live authority.",
            (
                "core/api/runtime_api.py",
                "core/apps/runtime_requests.py",
                "core/runtime/authority_service.py",
                "core/runtime/provider_start_handoff.py",
                "core/runtime/provider_step_admission.py",
                "core/runtime/remote_agentic_admission.py",
                "core/runtime/turn_queue_admission.py",
                "core/runtime/workspace_api_token.py",
            ),
            (
                "core.observability",
                "core.recovery",
                "core.shared",
                "core.usage",
            ),
        ),
        CertifiedTcbDependencyContract(
            "provider-input-composition",
            "Canonical source composition and provider request projection.",
            (
                "core/runtime/app_reference_classification.py",
                "core/runtime/attachment_projection.py",
                "core/runtime/provider_input_context.py",
                "core/runtime/provider_input_admission.py",
                "core/runtime/semantic_context_blocks.py",
                "core/runtime/semantic_envelope.py",
                "core/runtime/semantic_envelope_models.py",
                "core/runtime/semantic_tool_blocks.py",
                "core/runtime/workspace_instructions.py",
                "core/runtime/hosted_agentic_request.py",
                "core/runtime/hosted_agentic_stream.py",
                "core/runtime/hosted_agentic_transport.py",
                "core/runtime/classification_authority.py",
                "core/runtime/hosted_transport_security_probe.py",
                "core/runtime/hosted_transport_security_probe_support.py",
                "core/runtime/hosted_context_management.py",
                "core/runtime/hosted_harness_recipes.py",
                "core/runtime/hosted_provider_runtime.py",
                "core/runtime/hosted_runtime_registry_builder.py",
                "core/providers/google_interactions_request.py",
                "core/providers/google_interactions_catalog.py",
                "core/providers/hosted_context_compactors.py",
                "core/providers/hosted_endpoint_preflight.py",
                "core/providers/openrouter_agentic_catalog.py",
                "core/providers/openrouter_agentic_request.py",
            ),
            ("core.inter_agent",),
        ),
        CertifiedTcbDependencyContract(
            "classification-egress",
            "Resource classification, restrictive joins, transforms, decisions, and audit.",
            (
                "core/egress/agentic_policy.py",
                "core/egress/classification.py",
                "core/runtime/hosted_agentic_request.py",
                "core/runtime/classification_authority.py",
                "core/runtime/content_data_classification.py",
                "core/runtime/public_content_authority_store.py",
                "core/workspaces/data_governance.py",
            ),
            ("core.egress", "core.observability", "core.workspaces"),
        ),
        CertifiedTcbDependencyContract(
            "tool-execution",
            "Certified catalog/schema, confinement, invocation, ledger, and classified results.",
            (
                "core/runtime/confined_filesystem.py",
                "core/runtime/confined_filesystem_batch.py",
                "core/runtime/confined_filesystem_delete.py",
                "core/runtime/confined_filesystem_metadata.py",
                "core/runtime/confined_filesystem_mutation_support.py",
                "core/runtime/confined_filesystem_mutations.py",
                "core/runtime/confined_filesystem_search.py",
                "core/runtime/full_workspace_contract.py",
                "core/runtime/hosted_result_authority_guard.py",
                "core/runtime/hosted_result_security_behavior.py",
                "core/runtime/hosted_tool_security_probes.py",
                "core/runtime/hosted_workspace_effect_security_probe.py",
                "core/runtime/hosted_process_output.py",
                "core/runtime/hosted_tool_process_registry.py",
                "core/runtime/hosted_workspace_effect_support.py",
                "core/runtime/hosted_workspace_effects.py",
                "core/runtime/hosted_workspace_shell.py",
                "core/runtime/hosted_agentic_loop.py",
                "core/runtime/hosted_agentic_tool_execution.py",
                "core/runtime/hosted_agentic_tool_results.py",
                "core/runtime/hosted_tool_result_admission.py",
                "core/runtime/provider_step_journal.py",
                "core/runtime/tool_ledger.py",
                "core/runtime/tool_catalog.py",
                "core/runtime/tool_core_capabilities.py",
                "core/runtime/tool_discovery_capabilities.py",
                "core/runtime/tool_discovery_support.py",
                "core/runtime/tool_full_workspace_capabilities.py",
                "core/runtime/tool_full_workspace_schemas.py",
                "core/runtime/tool_full_workspace_support.py",
                "core/runtime/tool_orchestrator.py",
                "core/runtime/tool_process_capabilities.py",
                "core/runtime/tool_result_artifacts.py",
            ),
            ("core.runtime",),
        ),
        CertifiedTcbDependencyContract(
            "provider-state-lifecycle",
            "Private/provider state, continuation lifecycle, certificate authority, and dispatch.",
            (
                "core/providers/certificate_projection.py",
                "core/providers/certificate_service.py",
                "core/runtime/lifecycle_service.py",
                "core/runtime/hosted_agentic_lifecycle.py",
                "core/runtime/hosted_agentic_engine.py",
                "core/runtime/hosted_agentic_recovery.py",
                "core/runtime/provider_private_state.py",
                "core/runtime/provider_step_journal.py",
                "core/runtime/provider_step_models.py",
                "core/runtime/provider_state_service.py",
                "core/runtime/runtime_process_lifecycle.py",
                "core/runtime/turn_submission.py",
                "core/runtime/turn_submission_service_events.py",
                "core/runtime/turn_submission_service_output_text.py",
                "core/recovery/backend_restart.py",
                "core/recovery/continuation_fork.py",
            ),
            ("core.providers", "core.recovery", "core.runtime"),
        ),
        CertifiedTcbDependencyContract(
            "served-governance",
            "Server projection and the exact Chat/Settings source and built assets served to users.",
            (
                "apps/chat/backend/chat_state.py",
                "core/api/provider_api.py",
                "core/api/settings_api.py",
            ),
            ("core.app_sdk",),
            (
                "apps/chat/backend/app_backend.py",
                "apps/chat/frontend/src/App.tsx",
                "apps/chat/frontend/dist/index.html",
                "apps/settings/frontend/src/settingsPanel.ts",
                "apps/settings/frontend/dist/index.html",
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
    live_digest, _revision_fence = _compute_certified_tcb_snapshot(
        repository_root
    )
    return CertifiedTcbIdentity(
        manifest_id=CERTIFIED_EXECUTION_TCB.manifest_id,
        manifest_version=CERTIFIED_EXECUTION_TCB.manifest_version,
        structure_digest=CERTIFIED_EXECUTION_TCB.structure_digest,
        live_digest=live_digest,
    )


def audit_certified_tcb_dependencies(
    root: Path,
    *,
    manifest: CertifiedExecutionTcbManifest = CERTIFIED_EXECUTION_TCB,
) -> CertifiedTcbDependencyReport:
    """Audit the canonical manifest without exposing dependency paths publicly."""
    return _audit_certified_tcb_dependencies(root, manifest=manifest)


def compute_certified_tcb_digest(root: Path) -> str:
    """Hash the manifest structure and every regular file under its path roots."""
    live_digest, _revision_fence = _compute_certified_tcb_snapshot(root)
    return live_digest


def certified_tcb_revision_fence(root: Path | None = None) -> str:
    """Hash cheap filesystem identities for reliable live-digest invalidation."""
    repository_root = (
        root or Path(__file__).resolve().parents[2]
    ).resolve(strict=True)
    files = _collect_certified_tcb_files(repository_root)
    return _certified_tcb_revision_fence(files)


def _compute_certified_tcb_snapshot(root: Path) -> tuple[str, str]:
    """Return a content digest and its stable before/after filesystem fence."""
    repository_root = root.resolve(strict=True)
    files = _collect_certified_tcb_files(repository_root)
    revision_fence = _certified_tcb_revision_fence(files)
    digest = hashlib.sha256()
    digest.update(b"maverick.certified-execution-tcb.v9\x00")
    digest.update(CERTIFIED_EXECUTION_TCB.structure_digest.encode("ascii"))
    digest.update(b"\x00")
    for relative_path in sorted(files):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\x00")
        try:
            digest.update(Path(files[relative_path][0]).read_bytes())
        except OSError as error:
            raise CapabilityCertificateError("certificate_tcb_artifact_unavailable") from error
        digest.update(b"\x00")
    live_digest = digest.hexdigest()
    _require_dependency_audit(repository_root, live_digest=live_digest)
    final_files = _collect_certified_tcb_files(repository_root)
    final_fence = _certified_tcb_revision_fence(final_files)
    if final_fence != revision_fence:
        raise CapabilityCertificateError(
            "certificate_tcb_artifact_changed"
        )
    return live_digest, final_fence


def _collect_certified_tcb_files(
    repository_root: Path,
) -> dict[str, tuple[str, os.stat_result]]:
    """Collect exact artifacts and metadata with one non-following scan."""
    files: dict[str, tuple[str, os.stat_result]] = {}
    repository_root_string = os.fspath(repository_root)
    covered_directories: list[str] = []
    artifact_roots = sorted(
        set(CERTIFIED_EXECUTION_TCB.artifact_paths),
        key=lambda value: (value.count("/"), value),
    )
    scan_roots: list[tuple[str, str]] = []
    for relative_root in artifact_roots:
        if (
            not relative_root
            or relative_root.startswith("/")
            or ".." in Path(relative_root).parts
            or "\x00" in relative_root
        ):
            raise CapabilityCertificateError(
                "certificate_tcb_manifest_path_invalid"
            )
        if any(
            relative_root == directory
            or relative_root.startswith(directory + "/")
            for directory in covered_directories
        ):
            continue
        candidate = os.path.join(repository_root_string, relative_root)
        try:
            metadata = os.lstat(candidate)
        except OSError as error:
            raise CapabilityCertificateError(
                "certificate_tcb_artifact_missing"
            ) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise CapabilityCertificateError(
                "certificate_tcb_artifact_symlink"
            )
        if stat.S_ISREG(metadata.st_mode):
            if not relative_root.endswith((".pyc", ".pyo")):
                files[relative_root] = (candidate, metadata)
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise CapabilityCertificateError(
                "certificate_tcb_artifact_invalid"
            )
        covered_directories.append(relative_root)
        scan_roots.append((relative_root, candidate))
    stack = list(reversed(scan_roots))
    while stack:
        relative_directory, directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
        except OSError as error:
            raise CapabilityCertificateError(
                "certificate_tcb_artifact_unavailable"
            ) from error
        for entry in children:
            if entry.name in {"__pycache__", "node_modules", ".git"}:
                continue
            relative_path = f"{relative_directory}/{entry.name}"
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise CapabilityCertificateError(
                    "certificate_tcb_artifact_unavailable"
                ) from error
            if stat.S_ISLNK(metadata.st_mode):
                raise CapabilityCertificateError(
                    "certificate_tcb_artifact_symlink"
                )
            if stat.S_ISDIR(metadata.st_mode):
                stack.append((relative_path, entry.path))
            elif stat.S_ISREG(metadata.st_mode) and not entry.name.endswith(
                (".pyc", ".pyo")
            ):
                files[relative_path] = (entry.path, metadata)
    if not files:
        raise CapabilityCertificateError("certificate_tcb_artifact_empty")
    return files


def _certified_tcb_revision_fence(
    files: dict[str, tuple[str, os.stat_result]],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"maverick.certified-execution-tcb.revision-fence.v1\x00")
    digest.update(CERTIFIED_EXECUTION_TCB.structure_digest.encode("ascii"))
    digest.update(b"\x00")
    for relative_path in sorted(files):
        _path, metadata = files[relative_path]
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(
            struct.pack(
                "!4Q2q",
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
        )
        digest.update(b"\x00")
    return digest.hexdigest()


def _require_dependency_audit(repository_root: Path, *, live_digest: str) -> None:
    """Audit once per exact content identity while still rehashing every authority check."""
    key = (
        str(repository_root),
        CERTIFIED_EXECUTION_TCB.structure_digest,
        live_digest,
    )
    with _DEPENDENCY_AUDIT_CACHE_LOCK:
        if key in _DEPENDENCY_AUDIT_CACHE:
            _DEPENDENCY_AUDIT_CACHE.move_to_end(key)
            return
    audit_certified_tcb_dependencies(repository_root)
    with _DEPENDENCY_AUDIT_CACHE_LOCK:
        _DEPENDENCY_AUDIT_CACHE[key] = None
        _DEPENDENCY_AUDIT_CACHE.move_to_end(key)
        while len(_DEPENDENCY_AUDIT_CACHE) > _DEPENDENCY_AUDIT_CACHE_LIMIT:
            _DEPENDENCY_AUDIT_CACHE.popitem(last=False)


def validate_remote_tcb_identity(
    *,
    manifest_id: str,
    manifest_version: str,
    structure_digest: str,
    live_digest: str,
    root: Path | None = None,
) -> CertifiedTcbIdentity:
    """Require an exact current TCB identity for any hosted remote authority."""
    current, _revision_fence = validate_remote_tcb_identity_with_revision_fence(
        manifest_id=manifest_id,
        manifest_version=manifest_version,
        structure_digest=structure_digest,
        live_digest=live_digest,
        root=root,
    )
    return current


def validate_remote_tcb_identity_with_revision_fence(
    *,
    manifest_id: str,
    manifest_version: str,
    structure_digest: str,
    live_digest: str,
    root: Path | None = None,
) -> tuple[CertifiedTcbIdentity, str]:
    """Validate content and return the cheap fence bound to that exact read."""
    if not all((manifest_id, manifest_version, structure_digest, live_digest)):
        raise CapabilityCertificateError("certificate_tcb_identity_missing")
    repository_root = root or Path(__file__).resolve().parents[2]
    current_live_digest, revision_fence = _compute_certified_tcb_snapshot(
        repository_root
    )
    current = CertifiedTcbIdentity(
        manifest_id=CERTIFIED_EXECUTION_TCB.manifest_id,
        manifest_version=CERTIFIED_EXECUTION_TCB.manifest_version,
        structure_digest=CERTIFIED_EXECUTION_TCB.structure_digest,
        live_digest=current_live_digest,
    )
    if (
        manifest_id != current.manifest_id
        or manifest_version != current.manifest_version
        or structure_digest != current.structure_digest
    ):
        raise CapabilityCertificateError("certificate_tcb_identity_mismatch")
    if live_digest != current.live_digest:
        raise CapabilityCertificateError("certificate_tcb_drift")
    return current, revision_fence


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
