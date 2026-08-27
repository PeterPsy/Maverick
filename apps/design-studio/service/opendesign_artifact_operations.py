"""Governed OpenDesign artifact status, audit, repair, bootstrap, and diagnostics."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any, Iterator
from uuid import uuid4

from core.apps.artifact_mounts import (
    create_artifact_namespace,
    platform_artifact_store_root,
    provision_artifact_namespace,
)
from core.api.sidecar_control import request_sidecar_control
from core.shared.repository import discover_repository_root
from core.workspaces.paths import validate_workspace_id
from opendesign_artifact import (
    ArtifactError,
    is_sha256,
    selected_asset,
    sha256_file,
    write_canonical_json,
)
from opendesign_artifact_audit import (
    fully_audited_runtime,
    fully_audited_web_overlay_for_any_runtime,
)
from opendesign_artifact_store import ArtifactStoreError, OpenDesignArtifactStore, StoredArtifact
from opendesign_bootstrap import bootstrap_empty_generation
from opendesign_generation_control import load_generation_control_metadata
from opendesign_runtime_sources import (
    RUNTIME_SOURCE_CATALOG_PATH,
    RuntimeArtifactSource,
    RuntimeSourceCatalog,
    load_runtime_source_catalog,
)
from opendesign_web_overlay import VerifiedWebOverlay


SERVICE_ROOT = Path(__file__).resolve().parent
ARTIFACT_SOURCE_ROOT = Path(
    os.environ.get("MAVERICK_OPENDESIGN_ARTIFACT_SOURCE_ROOT", SERVICE_ROOT / "artifacts")
).resolve(strict=False)
SELECTION_PATH = SERVICE_ROOT / "opendesign_release_selection.json"
TRUST_CONTRACT_PATH = SERVICE_ROOT / "opendesign_web_trust.json"
APP_ID = "design-studio"
ARTIFACT_ID = "opendesign"
FULL_AUDIT_INTERVAL_SECONDS = 6 * 60 * 60
AUTHORITY_COMMAND_ENV = "MAVERICK_APP_ARTIFACT_AUTHORITY_COMMAND"
AUTHORITY_OPERATIONS = frozenset({"verify", "repair", "provision", "gc", "publish-web"})


@dataclass(frozen=True)
class RequiredArtifacts:
    current_runtime: str
    active_runtime: str
    rollback_runtime: str
    active_web: str
    optional_runtime: tuple[str, ...]
    web_overlays: tuple[str, ...]
    fresh_web_overlay: str
    required_runtime_artifacts: tuple[str, ...] = ()
    runtime_web_bindings: tuple[tuple[str, str], ...] = ()
    workspace_ids: tuple[str, ...] = ()
    workspace_reference_sha256: str = ""


def run_artifact_operation(
    operation: str,
    *,
    data_root: Path,
    workspace_id: str = "default",
    repository_root: Path | None = None,
    auto: bool = False,
    audit_workers: int | None = None,
    candidate_path: Path | None = None,
    candidate_digest: str | None = None,
    _authority: bool = False,
) -> dict[str, Any]:
    """Run one bounded operator action and return redaction-safe JSON."""
    repository = discover_repository_root(start_path=repository_root or SERVICE_ROOT)
    started = time.monotonic()
    if operation not in {"status", "verify", "repair", "provision", "prewarm", "diagnostics", "gc", "publish-web"}:
        raise ArtifactStoreError("runtime_binding_invalid", "artifact_operation", "Unsupported artifact operation")
    if operation == "prewarm":
        return _prewarm(repository, workspace_id=workspace_id)
    if operation == "diagnostics":
        return _diagnostics(repository, data_root=data_root)
    if operation in AUTHORITY_OPERATIONS and not _authority and not _is_artifact_authority(repository):
        result = _invoke_artifact_authority(
            operation,
            repository=repository,
            workspace_id=workspace_id,
            auto=auto,
            audit_workers=audit_workers,
            candidate_path=candidate_path,
            candidate_digest=candidate_digest,
        )
        if operation in {"repair", "provision"}:
            return _bootstrap_after_authority(
                result,
                repository=repository,
                data_root=data_root,
            )
        return result

    namespace = _namespace(
        repository,
        create=operation in {"repair", "provision", "gc", "publish-web"},
        authority=_authority,
    )
    store = OpenDesignArtifactStore(namespace)
    staging_recovery = (
        store.recover_orphaned_staging()
        if operation in {"repair", "provision", "publish-web"}
        else None
    )
    if operation == "publish-web":
        result = _publish_web_candidate(
            store,
            candidate_path=candidate_path,
            candidate_digest=candidate_digest,
        )
        _append_audit(
            store.root,
            operation=operation,
            status="succeeded",
            duration_ms=_elapsed_ms(started),
            error_code=None,
            auto=auto,
        )
        return {
            "schema_version": "1",
            "operation": operation,
            "status": "ready",
            "duration_ms": _elapsed_ms(started),
            "store_generation": store.store_generation,
            **({"staging_recovery": staging_recovery} if staging_recovery is not None else {}),
            **result,
        }
    runtime_sources = load_runtime_source_catalog()
    manifest = runtime_sources.by_role["current"].manifest
    global_operation = operation in {"verify", "repair", "provision", "gc"} and (
        _authority or _is_artifact_authority(repository)
    )
    reference_lock = (
        _workspace_reference_lock(store, exclusive=operation != "verify")
        if global_operation
        else nullcontext()
    )
    repair_lock = (
        _repair_operation_lock(store)
        if operation in {"repair", "provision"}
        else nullcontext()
    )
    required: RequiredArtifacts | None = None
    try:
        with repair_lock:
            with reference_lock:
                if global_operation:
                    required = _global_required_artifacts(
                        repository,
                        requested_workspace_id=workspace_id,
                        manifest=manifest,
                    )
                else:
                    required = _required_artifacts(data_root, manifest=manifest)
                _validate_required_runtime_sources(required, runtime_sources=runtime_sources)
                if operation in {"repair", "provision"}:
                    result = _repair(
                        store,
                        required=required,
                        runtime_sources=runtime_sources,
                    )
                elif operation == "verify":
                    result = _verify(store, required=required, max_workers=audit_workers)
                elif operation == "gc":
                    result = _garbage_collect(store, required=required)
                else:
                    result = _status(store, required=required)
                if required.workspace_reference_sha256:
                    result = {
                        **result,
                        "workspace_ids": list(required.workspace_ids),
                        "workspace_reference_sha256": required.workspace_reference_sha256,
                    }
                if operation in {"provision", "repair", "verify"}:
                    _record_full_audit_success(
                        store.root,
                        operation=operation,
                        result=result,
                        store_generation=store.store_generation,
                    )
                if operation != "status":
                    _append_audit(
                        store.root,
                        operation=operation,
                        status="succeeded",
                        duration_ms=_elapsed_ms(started),
                        error_code=None,
                        auto=auto,
                    )
    except Exception as error:
        if operation != "status":
            if operation in {"provision", "repair", "verify"}:
                _record_full_audit_failure(
                    store.root,
                    error=error,
                    store_generation=store.store_generation,
                    required=required,
                )
            _append_audit(
                store.root,
                operation=operation,
                status="failed",
                duration_ms=_elapsed_ms(started),
                error_code=getattr(error, "code", type(error).__name__),
                auto=auto,
            )
        raise
    return {
        "schema_version": "1",
        "operation": operation,
        "status": "ready",
        "duration_ms": _elapsed_ms(started),
        "store_generation": store.store_generation,
        **({"staging_recovery": staging_recovery} if staging_recovery is not None else {}),
        **result,
    }


def _publish_web_candidate(
    store: OpenDesignArtifactStore,
    *,
    candidate_path: Path | None,
    candidate_digest: str | None,
) -> dict[str, Any]:
    if candidate_path is None or candidate_digest is None or not is_sha256(candidate_digest):
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "artifact_submission",
            "The OpenDesign web submission identity is invalid",
        )
    try:
        candidate = Path(candidate_path)
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError("submission root is not a real directory")
        source = candidate.resolve(strict=True)
    except OSError as error:
        raise ArtifactStoreError(
            "artifact_missing",
            "artifact_submission",
            "The OpenDesign web submission is unavailable",
        ) from error
    if not source.is_dir() or source.is_symlink():
        raise ArtifactStoreError(
            "artifact_missing",
            "artifact_submission",
            "The OpenDesign web submission is unavailable",
        )
    stored = store.publish_web_overlay(
        source,
        web_overlay_sha256=candidate_digest,
        trust_contract=TRUST_CONTRACT_PATH,
    )
    store.full_audit("web", candidate_digest, trust_contract=TRUST_CONTRACT_PATH)
    return {
        "web_overlay_sha256": stored.artifact_sha256,
        "compatible_runtime_artifact_sha256": list(
            stored.receipt["compatible_runtime_artifact_sha256"]
        ),
    }


def _record_full_audit_success(
    store_root: Path,
    *,
    operation: str,
    result: dict[str, Any],
    store_generation: str,
    observed_at_epoch_ms: int | None = None,
) -> None:
    """Let the background scheduler reuse the mandatory lifecycle full audit."""
    observed = (
        int(time.time() * 1000)
        if observed_at_epoch_ms is None
        else observed_at_epoch_ms
    )
    if operation == "verify":
        runtime_count = len(result.get("audited_runtime", []))
        web_count = len(result.get("audited_web", []))
    else:
        runtime_count = len(result.get("retained_runtime_artifacts", []))
        web_count = len(result.get("retained_web_overlays", []))
    workspace_ids = result.get("workspace_ids")
    reference_sha256 = result.get("workspace_reference_sha256")
    if (
        not isinstance(workspace_ids, list)
        or not workspace_ids
        or any(not isinstance(item, str) for item in workspace_ids)
        or not is_sha256(reference_sha256)
    ):
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "artifact_audit_coverage",
            "The global artifact audit did not bind its workspace reference set",
        )
    path = store_root / "audit/background-full-audit.json"
    _ensure_readable_audit_root(path.parent)
    write_canonical_json(
        path,
        {
            "schema_version": "3",
            "status": "passed",
            "attempted_at_epoch_ms": observed,
            "verified_at_epoch_ms": observed,
            "next_attempt_at_epoch_ms": observed + FULL_AUDIT_INTERVAL_SECONDS * 1000,
            "store_generation": store_generation,
            "runtime_count": runtime_count,
            "web_count": web_count,
            "workspace_ids": workspace_ids,
            "workspace_reference_sha256": reference_sha256,
            "auto_repair_requested": False,
            "audit_error_code": None,
            "audit_phase": None,
            "recovery_error_code": None,
            "recovery_phase": None,
        },
    )
    path.chmod(0o444)


def _record_full_audit_failure(
    store_root: Path,
    *,
    error: BaseException,
    store_generation: str,
    required: RequiredArtifacts | None,
    observed_at_epoch_ms: int | None = None,
) -> None:
    observed = (
        int(time.time() * 1000)
        if observed_at_epoch_ms is None
        else observed_at_epoch_ms
    )
    code = _safe_audit_token(
        getattr(error, "code", None),
        default="artifact_integrity_mismatch",
    )
    phase = _safe_audit_token(
        getattr(error, "phase", None),
        default="artifact_full_verify",
    )
    path = store_root / "audit/background-full-audit.json"
    workspace_ids = list(required.workspace_ids) if required is not None else []
    reference_sha256 = (
        required.workspace_reference_sha256
        if required is not None and is_sha256(required.workspace_reference_sha256)
        else None
    )
    _ensure_readable_audit_root(path.parent)
    write_canonical_json(
        path,
        {
            "schema_version": "3",
            "status": "failed",
            "attempted_at_epoch_ms": observed,
            "verified_at_epoch_ms": None,
            "next_attempt_at_epoch_ms": observed + 60 * 60 * 1000,
            "store_generation": store_generation,
            "runtime_count": 0,
            "web_count": 0,
            "workspace_ids": workspace_ids,
            "workspace_reference_sha256": reference_sha256,
            "auto_repair_requested": True,
            "audit_error_code": code,
            "audit_phase": phase,
            "recovery_error_code": None,
            "recovery_phase": None,
        },
    )
    path.chmod(0o444)


def _safe_audit_token(value: object, *, default: str) -> str:
    if (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0] in "abcdefghijklmnopqrstuvwxyz"
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value)
    ):
        return value
    return default


def _ensure_readable_audit_root(path: Path) -> None:
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    path.chmod(0o755)


@contextmanager
def _repair_operation_lock(store: OpenDesignArtifactStore) -> Iterator[None]:
    """Reject overlapping repair workflows before either mutates a package."""
    path = store.root / ".locks/artifact-repair.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o640)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ArtifactStoreError(
                "artifact_repairing",
                "repair_lock",
                "Another governed OpenDesign repair is already running",
            ) from error
        yield
    finally:
        os.close(descriptor)


@contextmanager
def _workspace_reference_lock(
    store: OpenDesignArtifactStore,
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Freeze control commits across a global reference scan and its result."""
    path = store.root / ".locks/workspace-references.lock"
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _repair(
    store: OpenDesignArtifactStore,
    *,
    required: RequiredArtifacts,
    runtime_sources: RuntimeSourceCatalog,
    data_root: Path | None = None,
) -> dict[str, Any]:
    # Retained for direct verifier callers; workspace mutation is intentionally
    # performed by _bootstrap_after_authority on the service side.
    del data_root
    current_source = runtime_sources.source_for_digest(required.current_runtime)
    if current_source is None:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "runtime_source_catalog",
            "The current OpenDesign runtime has no exact materialization source",
        )
    runtime, runtime_repaired = _retain_or_repair_runtime(
        store,
        digest=required.current_runtime,
        source=current_source,
        required=True,
    )
    retained_runtime: list[str] = [runtime.artifact_sha256]
    repaired_runtime: list[str] = [runtime.artifact_sha256] if runtime_repaired else []
    required_runtime = {
        required.current_runtime,
        required.active_runtime,
        required.rollback_runtime,
        *required.required_runtime_artifacts,
    }
    for digest in _runtime_references(required):
        if digest == required.current_runtime:
            continue
        retained, repaired = _retain_or_repair_runtime(
            store,
            digest=digest,
            source=runtime_sources.source_for_digest(digest),
            required=digest in required_runtime,
        )
        if retained is None:
            continue
        retained_runtime.append(digest)
        if repaired:
            repaired_runtime.append(digest)
    repaired_web: list[str] = []
    retained_web: list[str] = []
    runtime_candidates = _runtime_references(required)
    for digest in required.web_overlays:
        web_invalid_identity = _known_invalid_identity(store, kind="web", digest=digest)
        if web_invalid_identity is None:
            try:
                fully_audited_web_overlay_for_any_runtime(
                    store,
                    digest,
                    runtime_artifact_sha256=runtime_candidates,
                    trust_contract=TRUST_CONTRACT_PATH,
                )
            except ArtifactStoreError:
                web_invalid_identity = store.package_identity("web", digest)
            else:
                retained_web.append(digest)
                continue
        source = ARTIFACT_SOURCE_ROOT / "open-design-web" / digest
        if not source.is_dir() or source.is_symlink():
            raise ArtifactStoreError(
                "artifact_missing",
                "repair_source_verify",
                "The pinned signed OpenDesign web repair source is unavailable",
            )
        web_invalid_identity = web_invalid_identity or store.package_identity("web", digest)
        store.publish_web_overlay(
            source,
            web_overlay_sha256=digest,
            trust_contract=TRUST_CONTRACT_PATH,
            repair=True,
            invalid_package_identity=web_invalid_identity,
        )
        fully_audited_web_overlay_for_any_runtime(
            store,
            digest,
            runtime_artifact_sha256=runtime_candidates,
            trust_contract=TRUST_CONTRACT_PATH,
        )
        _clear_invalid_marker(store, kind="web", digest=digest)
        repaired_web.append(digest)
        retained_web.append(digest)
    _validate_runtime_web_bindings(store, required=required)
    return {
        "runtime_artifact_sha256": runtime.artifact_sha256,
        "runtime_repaired": runtime_repaired,
        "repaired_runtime_artifacts": repaired_runtime,
        "retained_runtime_artifacts": retained_runtime,
        "web_overlay_sha256": required.fresh_web_overlay,
        "repaired_web_overlays": repaired_web,
        "retained_web_overlays": retained_web,
        # Workspace data belongs to the ordinary service principal.  The
        # authority returns only immutable store identities; the client creates
        # a fresh data generation after it has reopened those identities on the
        # read-only side of the boundary.
        "data_generation_bootstrapped": False,
    }


def _retain_or_repair_runtime(
    store: OpenDesignArtifactStore,
    *,
    digest: str,
    source: RuntimeArtifactSource | None,
    required: bool,
) -> tuple[StoredArtifact | None, bool]:
    invalid_identity = _known_invalid_identity(store, kind="runtime", digest=digest)
    try:
        if invalid_identity is not None:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "audited_repair_handoff",
                "OpenDesign runtime was rejected by a prior full audit",
            )
        stored = _fully_audited_runtime_source(store, digest=digest, source=source)
        return stored, False
    except ArtifactStoreError as error:
        if source is None:
            if required:
                raise ArtifactStoreError(
                    "artifact_missing",
                    "repair_source_verify",
                    "A required OpenDesign runtime has no pinned repair source",
                ) from error
            return None, False
    invalid_identity = invalid_identity or store.package_identity("runtime", digest)
    try:
        artifact_directory = source.artifact_directory(ARTIFACT_SOURCE_ROOT)
    except ArtifactError as error:
        raise ArtifactStoreError(
            "artifact_missing",
            "repair_source_verify",
            "The exact signed OpenDesign runtime repair source is unavailable",
        ) from error
    published = store.publish_runtime(
        artifact_directory,
        manifest=source.manifest,
        repair=True,
        invalid_package_identity=invalid_identity,
        artifact_verifier=source.verify_artifact_directory,
    )
    if published.artifact_sha256 != digest:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "repair",
            "Published runtime differs from its source-catalog digest",
        )
    stored = _fully_audited_runtime_source(store, digest=digest, source=source)
    _clear_invalid_marker(store, kind="runtime", digest=digest)
    return stored, True


def _fully_audited_runtime_source(
    store: OpenDesignArtifactStore,
    *,
    digest: str,
    source: RuntimeArtifactSource | None,
) -> StoredArtifact:
    if source is None:
        return fully_audited_runtime(
            store,
            digest,
            file_manifest_sha256=None,
            opendesign_version="0.16.1",
            upstream_commit=None,
        )
    asset = selected_asset(source.manifest, require_artifact_digest=True)
    return fully_audited_runtime(
        store,
        digest,
        file_manifest_sha256=str(asset["file_manifest_sha256"]),
        opendesign_version=str(source.manifest["upstream"]["release_version"]),
        upstream_commit=str(source.manifest["upstream"]["commit"]),
    )


def _status(store: OpenDesignArtifactStore, *, required: RequiredArtifacts) -> dict[str, Any]:
    runtime_health: dict[str, dict[str, object]] = {}
    runtime_states: dict[str, str] = {}
    for digest in _runtime_references(required):
        observed = store.fast_runtime_health(
            digest,
            file_manifest_sha256=None,
            opendesign_version="0.16.1",
            upstream_commit=None,
        )
        runtime_health[digest] = observed
        runtime_states[digest] = str(observed["state"])
    web_states: dict[str, str] = {}
    for digest in required.web_overlays:
        last_state = "artifact_missing"
        for runtime_digest in _runtime_references(required):
            observed = store.fast_web_overlay_health(
                digest,
                runtime_artifact_sha256=runtime_digest,
            )
            last_state = str(observed["state"])
            if observed["verified"] is True:
                web_states[digest] = "verified_fast"
                break
        else:
            web_states[digest] = last_state
    active_runtime = runtime_health[required.active_runtime]
    active_web = store.fast_web_overlay_health(
        required.active_web,
        runtime_artifact_sha256=required.active_runtime,
    )
    active_health = {
        "artifact_available": (
            active_runtime["available"] is True and active_web["available"] is True
        ),
        "artifact_verified": (
            active_runtime["verified"] is True and active_web["verified"] is True
        ),
        "artifact_protected": (
            active_runtime["protected"] is True and active_web["protected"] is True
        ),
    }
    active_failure = next(
        (
            observed
            for observed in (active_runtime, active_web)
            if observed["state"] != "verified_fast"
        ),
        None,
    )
    binding_states = _runtime_web_binding_states(store, required=required)
    operational = all(active_health.values())
    retained = all(
        state == "verified_fast"
        for state in (
            *runtime_states.values(),
            *web_states.values(),
            *binding_states.values(),
        )
    )
    return {
        "operational": operational,
        "retention_complete": retained,
        "runtime": runtime_states,
        "web": web_states,
        "runtime_web_bindings": binding_states,
        "health": active_health,
        "active": {
            "runtime_artifact_sha256": required.active_runtime,
            "web_overlay_sha256": required.active_web,
            "runtime": active_runtime,
            "web": active_web,
        },
        "active_error_code": (
            str(active_failure["state"]) if active_failure is not None else None
        ),
        "active_error_phase": (
            str(active_failure["phase"]) if active_failure is not None else None
        ),
    }


def _runtime_web_binding_states(
    store: OpenDesignArtifactStore,
    *,
    required: RequiredArtifacts,
) -> dict[str, str]:
    states: dict[str, str] = {}
    for runtime_digest, web_digest in required.runtime_web_bindings:
        identity = f"{runtime_digest}:{web_digest}"
        try:
            store.fast_web_overlay(
                web_digest,
                runtime_artifact_sha256=runtime_digest,
            )
        except ArtifactStoreError as error:
            states[identity] = error.code
        else:
            states[identity] = "verified_fast"
    return states


def _validate_runtime_web_bindings(
    store: OpenDesignArtifactStore,
    *,
    required: RequiredArtifacts,
) -> None:
    for runtime_digest, web_digest in required.runtime_web_bindings:
        store.fast_web_overlay(
            web_digest,
            runtime_artifact_sha256=runtime_digest,
        )


def _verify(
    store: OpenDesignArtifactStore,
    *,
    required: RequiredArtifacts,
    max_workers: int | None = None,
) -> dict[str, Any]:
    audited_runtime: list[str] = []
    mandatory_runtime = {
        required.current_runtime,
        required.active_runtime,
        required.rollback_runtime,
        *required.required_runtime_artifacts,
    }
    for digest in _runtime_references(required):
        try:
            store.full_audit("runtime", digest, max_workers=max_workers)
        except ArtifactStoreError:
            _mark_invalid(store, kind="runtime", digest=digest)
            if digest in mandatory_runtime:
                raise
            continue
        _clear_invalid_marker(store, kind="runtime", digest=digest)
        audited_runtime.append(digest)
    audited_web: list[str] = []
    for digest in required.web_overlays:
        try:
            audited = store.full_audit(
                "web",
                digest,
                trust_contract=TRUST_CONTRACT_PATH,
                max_workers=max_workers,
            )
        except ArtifactStoreError:
            _mark_invalid(store, kind="web", digest=digest)
            raise
        _clear_invalid_marker(store, kind="web", digest=digest)
        audited_web.append(audited.artifact_sha256)
    _validate_runtime_web_bindings(store, required=required)
    status = _status(store, required=required)
    return {
        "operational": status["operational"],
        "retention_complete": status["retention_complete"],
        "audited_runtime": audited_runtime,
        "audited_web": audited_web,
    }


def _invalid_marker(store: OpenDesignArtifactStore, *, kind: str, digest: str) -> Path:
    return store.root / "audit" / f"invalid-{kind}-{digest}.json"


def _mark_invalid(store: OpenDesignArtifactStore, *, kind: str, digest: str) -> None:
    identity = store.package_identity(kind, digest)
    if identity is None:
        return
    path = _invalid_marker(store, kind=kind, digest=digest)
    _ensure_readable_audit_root(path.parent)
    write_canonical_json(
        path,
        {
            "schema_version": "1",
            "kind": kind,
            "artifact_sha256": digest,
            "store_generation": store.store_generation,
            "package_device": identity[0],
            "package_inode": identity[1],
            "observed_at_epoch_ms": int(time.time() * 1000),
        },
    )
    path.chmod(0o444)


def _known_invalid_identity(
    store: OpenDesignArtifactStore,
    *,
    kind: str,
    digest: str,
) -> tuple[int, int] | None:
    path = _invalid_marker(store, kind=kind, digest=digest)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "schema_version",
        "kind",
        "artifact_sha256",
        "store_generation",
        "package_device",
        "package_inode",
        "observed_at_epoch_ms",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_version") != "1"
        or payload.get("kind") != kind
        or payload.get("artifact_sha256") != digest
        or payload.get("store_generation") != store.store_generation
        or isinstance(payload.get("package_device"), bool)
        or not isinstance(payload.get("package_device"), int)
        or isinstance(payload.get("package_inode"), bool)
        or not isinstance(payload.get("package_inode"), int)
        or isinstance(payload.get("observed_at_epoch_ms"), bool)
        or not isinstance(payload.get("observed_at_epoch_ms"), int)
    ):
        return None
    identity = (int(payload["package_device"]), int(payload["package_inode"]))
    return identity if store.package_identity(kind, digest) == identity else None


def _clear_invalid_marker(store: OpenDesignArtifactStore, *, kind: str, digest: str) -> None:
    _invalid_marker(store, kind=kind, digest=digest).unlink(missing_ok=True)


def _required_artifacts(data_root: Path, *, manifest: dict[str, Any]) -> RequiredArtifacts:
    current = str(selected_asset(manifest, require_artifact_digest=True)["sha256"])
    release = _read_selection()
    rollback_runtime = str(release["rollback_runtime_artifact_sha256"])
    if rollback_runtime == current:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "release_selection",
            "The declared rollback runtime must differ from the current runtime",
        )
    active_runtime = current
    active_web = str(release["active_web_overlay_sha256"])
    optional_runtime: list[str] = []
    web = [str(release["active_web_overlay_sha256"]), str(release["rollback_web_overlay_sha256"])]
    bindings = [
        (current, str(release["active_web_overlay_sha256"])),
        (rollback_runtime, str(release["rollback_web_overlay_sha256"])),
    ]
    control_path = data_root / "opendesign" / "control.json"
    if control_path.exists() or control_path.is_symlink():
        try:
            control_metadata = control_path.lstat()
        except OSError as error:
            raise ArtifactStoreError(
                "runtime_binding_invalid",
                "workspace_reference_scan",
                "A Design Studio workspace control file is unavailable",
            ) from error
        if stat.S_ISLNK(control_metadata.st_mode) or not stat.S_ISREG(control_metadata.st_mode):
            raise ArtifactStoreError(
                "runtime_binding_invalid",
                "workspace_reference_scan",
                "A Design Studio workspace control path is unsafe",
            )
        control = load_generation_control_metadata(control_path.parent)
        active_runtime = control.active.runtime_artifact_sha256
        active_web = control.active.web_overlay_sha256
        for selection in (
            control.active,
            control.previous_release,
            control.previous_web,
            control.previous_runtime,
        ):
            if selection is None:
                continue
            bindings.append(
                (
                    selection.runtime_artifact_sha256,
                    selection.web_overlay_sha256,
                )
            )
            web.append(selection.web_overlay_sha256)
            if selection is not control.active:
                optional_runtime.append(selection.runtime_artifact_sha256)
    return RequiredArtifacts(
        current_runtime=current,
        active_runtime=active_runtime,
        rollback_runtime=rollback_runtime,
        active_web=active_web,
        optional_runtime=tuple(_unique(optional_runtime)),
        web_overlays=tuple(_unique(web)),
        fresh_web_overlay=str(release["active_web_overlay_sha256"]),
        runtime_web_bindings=tuple(dict.fromkeys(bindings)),
    )


def discover_design_studio_workspace_data_roots(
    repository: Path,
    *,
    requested_workspace_id: str,
) -> dict[str, Path]:
    """Return every canonical Design Studio data root in one installation."""
    repository = Path(repository).resolve(strict=True)
    try:
        requested = validate_workspace_id(requested_workspace_id)
    except ValueError as error:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "workspace_reference_scan",
            "The requested workspace identity is invalid",
        ) from error
    workspaces_root = repository / "workspaces"
    roots: dict[str, Path] = {
        requested: workspaces_root / requested / "data/design-studio",
    }
    if not workspaces_root.exists() and not workspaces_root.is_symlink():
        return roots
    try:
        workspaces_metadata = workspaces_root.lstat()
    except OSError as error:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "workspace_reference_scan",
            "The workspace registry is unavailable",
        ) from error
    if stat.S_ISLNK(workspaces_metadata.st_mode) or not stat.S_ISDIR(workspaces_metadata.st_mode):
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "workspace_reference_scan",
            "The workspace registry path is unsafe",
        )
    for workspace in sorted(workspaces_root.iterdir(), key=lambda item: item.name):
        try:
            metadata = workspace.lstat()
        except OSError as error:
            raise ArtifactStoreError(
                "runtime_binding_invalid",
                "workspace_reference_scan",
                "A workspace registry entry is unavailable",
            ) from error
        if not stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            continue
        try:
            workspace_id = validate_workspace_id(workspace.name)
        except ValueError as error:
            raise ArtifactStoreError(
                "runtime_binding_invalid",
                "workspace_reference_scan",
                "The workspace registry contains an invalid directory",
            ) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ArtifactStoreError(
                "runtime_binding_invalid",
                "workspace_reference_scan",
                "The workspace registry contains a symlink",
            )
        data = workspace / "data"
        app_data = data / "design-studio"
        if not app_data.exists() and not app_data.is_symlink():
            continue
        for path in (data, app_data):
            path_metadata = path.lstat()
            if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISDIR(path_metadata.st_mode):
                raise ArtifactStoreError(
                    "runtime_binding_invalid",
                    "workspace_reference_scan",
                    "A Design Studio workspace data root is unsafe",
                )
        roots[workspace_id] = app_data
    return dict(sorted(roots.items()))


def _global_required_artifacts(
    repository: Path,
    *,
    requested_workspace_id: str,
    manifest: dict[str, Any],
) -> RequiredArtifacts:
    roots = discover_design_studio_workspace_data_roots(
        repository,
        requested_workspace_id=requested_workspace_id,
    )
    workspace_requirements = {
        workspace_id: _required_artifacts(data_root, manifest=manifest)
        for workspace_id, data_root in roots.items()
    }
    requested = workspace_requirements[requested_workspace_id]
    required_runtime = {
        requested.current_runtime,
        requested.rollback_runtime,
        *(item.active_runtime for item in workspace_requirements.values()),
        *(
            digest
            for item in workspace_requirements.values()
            for digest in item.optional_runtime
        ),
    }
    web_overlays = {
        digest
        for item in workspace_requirements.values()
        for digest in item.web_overlays
    }
    runtime_web_bindings = {
        binding
        for item in workspace_requirements.values()
        for binding in item.runtime_web_bindings
    }
    coverage = {
        "schema_version": "1",
        "release": {
            "current_runtime": requested.current_runtime,
            "rollback_runtime": requested.rollback_runtime,
            "fresh_web_overlay": requested.fresh_web_overlay,
        },
        "workspaces": [
            {
                "workspace_id": workspace_id,
                "active_runtime": item.active_runtime,
                "active_web": item.active_web,
                "optional_runtime": sorted(item.optional_runtime),
                "web_overlays": sorted(item.web_overlays),
                "runtime_web_bindings": [
                    list(binding) for binding in sorted(item.runtime_web_bindings)
                ],
            }
            for workspace_id, item in workspace_requirements.items()
        ],
    }
    coverage_sha256 = hashlib.sha256(
        json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RequiredArtifacts(
        current_runtime=requested.current_runtime,
        active_runtime=requested.active_runtime,
        rollback_runtime=requested.rollback_runtime,
        active_web=requested.active_web,
        optional_runtime=(),
        web_overlays=tuple(sorted(web_overlays)),
        fresh_web_overlay=requested.fresh_web_overlay,
        required_runtime_artifacts=tuple(sorted(required_runtime)),
        runtime_web_bindings=tuple(sorted(runtime_web_bindings)),
        workspace_ids=tuple(workspace_requirements),
        workspace_reference_sha256=coverage_sha256,
    )


def global_artifact_reference_coverage(
    repository: Path,
    *,
    requested_workspace_id: str,
) -> dict[str, object]:
    """Return the global reference identity without opening artifact content."""
    runtime_sources = load_runtime_source_catalog()
    required = _global_required_artifacts(
        repository,
        requested_workspace_id=requested_workspace_id,
        manifest=runtime_sources.by_role["current"].manifest,
    )
    return {
        "workspace_ids": list(required.workspace_ids),
        "workspace_reference_sha256": required.workspace_reference_sha256,
    }


def _validate_required_runtime_sources(
    required: RequiredArtifacts,
    *,
    runtime_sources: RuntimeSourceCatalog,
) -> None:
    if runtime_sources.by_role["current"].artifact_sha256 != required.current_runtime:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "runtime_source_catalog",
            "The current runtime selection differs from its source catalog",
        )
    if runtime_sources.by_role["rollback"].artifact_sha256 != required.rollback_runtime:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "runtime_source_catalog",
            "The rollback runtime selection differs from its source catalog",
        )


def _bootstrap_fresh_generation(data_root: Path, *, runtime: StoredArtifact, web: StoredArtifact) -> bool:
    generation_root = data_root / "opendesign"
    if (generation_root / "control.json").exists() or (generation_root / "control.json").is_symlink():
        return False
    overlay = _verified_overlay(web)
    bootstrap_empty_generation(
        generation_root,
        artifact_sha256=runtime.artifact_sha256,
        web_overlay_sha256=web.artifact_sha256,
        opendesign_version=str(runtime.receipt["opendesign_version"]),
        verified_artifacts={runtime.artifact_sha256: str(runtime.receipt["opendesign_version"])},
        verified_overlays={web.artifact_sha256: overlay},
    )
    return True


def _bootstrap_after_authority(
    result: dict[str, Any],
    *,
    repository: Path,
    data_root: Path,
) -> dict[str, Any]:
    runtime_digest = result.get("runtime_artifact_sha256")
    web_digest = result.get("web_overlay_sha256")
    if not is_sha256(runtime_digest) or not is_sha256(web_digest):
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority returned an invalid materialization result",
        )
    namespace = create_artifact_namespace(
        repository_root=repository,
        app_id=APP_ID,
        artifact_id=ARTIFACT_ID,
    )
    store = OpenDesignArtifactStore(namespace)
    runtime = store.fast_runtime(runtime_digest)
    web = store.fast_web_overlay(
        web_digest,
        runtime_artifact_sha256=runtime_digest,
    )
    returned = dict(result)
    returned["data_generation_bootstrapped"] = _bootstrap_fresh_generation(
        data_root,
        runtime=runtime,
        web=web,
    )
    return returned


def _verified_overlay(stored: StoredArtifact) -> VerifiedWebOverlay:
    receipt = stored.receipt
    return VerifiedWebOverlay(
        web_overlay_sha256=stored.artifact_sha256,
        path=stored.content_path,
        static_dir=stored.content_path / "static",
        od_version=str(receipt["opendesign_version"]),
        upstream_commit=str(receipt["upstream_commit"]),
        compatible_runtime_artifact_sha256=frozenset(str(item) for item in receipt["compatible_runtime_artifact_sha256"]),
        file_manifest_sha256=str(receipt["source_file_manifest_sha256"]),
        toolchain_sha256="protected-store-receipt",
    )


def _namespace(repository: Path, *, create: bool, authority: bool = False) -> Path:
    if create:
        if authority:
            return provision_artifact_namespace(
                repository_root=repository,
                app_id=APP_ID,
                artifact_id=ARTIFACT_ID,
            )
        return create_artifact_namespace(
            repository_root=repository,
            app_id=APP_ID,
            artifact_id=ARTIFACT_ID,
        )
    namespace = platform_artifact_store_root(repository) / APP_ID / ARTIFACT_ID
    if not namespace.is_dir() or namespace.is_symlink():
        raise ArtifactStoreError("artifact_missing", "status", "The protected OpenDesign store is unavailable")
    return namespace


def _is_artifact_authority(repository: Path) -> bool:
    marker_path = (
        platform_artifact_store_root(repository)
        / APP_ID
        / ARTIFACT_ID
        / ".maverick-artifact-namespace.json"
    )
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        metadata = marker_path.stat()
    except (OSError, json.JSONDecodeError):
        return False
    owner_uid = payload.get("owner_uid") if isinstance(payload, dict) else None
    return (
        isinstance(owner_uid, int)
        and not isinstance(owner_uid, bool)
        and owner_uid == os.geteuid()
        and metadata.st_uid == os.geteuid()
    )


def _invoke_artifact_authority(
    operation: str,
    *,
    repository: Path,
    workspace_id: str,
    auto: bool,
    audit_workers: int | None,
    candidate_path: Path | None,
    candidate_digest: str | None,
) -> dict[str, Any]:
    command = _validated_authority_command(repository)
    sudo = shutil.which("sudo")
    if sudo is None:
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority cannot be invoked",
        )
    with _authority_web_submission(candidate_path) as submitted_path:
        payload = {
            "schema_version": "1",
            "operation": operation,
            "workspace_id": workspace_id,
            "auto": bool(auto),
            "audit_workers": audit_workers,
            "candidate_path": (
                None if submitted_path is None else str(submitted_path.absolute())
            ),
            "candidate_digest": candidate_digest,
        }
        try:
            completed = subprocess.run(
                [sudo, "-n", str(command)],
                input=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
                check=False,
                cwd=Path("/"),
                env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ArtifactStoreError(
                "artifact_authority_unavailable",
                "artifact_authority",
                "The platform artifact authority did not complete",
            ) from error
    try:
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority returned an invalid response",
        ) from error
    if completed.returncode != 0 or not isinstance(response, dict) or response.get("ok") is not True:
        code = response.get("error_code") if isinstance(response, dict) else None
        phase = response.get("phase") if isinstance(response, dict) else None
        raise ArtifactStoreError(
            str(code) if isinstance(code, str) and code else "artifact_authority_failed",
            str(phase) if isinstance(phase, str) and phase else "artifact_authority",
            "The platform artifact authority rejected the operation",
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority omitted its result",
        )
    return result


@contextmanager
def _authority_web_submission(candidate_path: Path | None) -> Iterator[Path | None]:
    """Create a non-secret, read-only handoff visible to the authority UID."""
    if candidate_path is None:
        yield None
        return
    source = Path(candidate_path)
    try:
        metadata = source.lstat()
    except OSError as error:
        raise ArtifactStoreError(
            "artifact_missing",
            "artifact_submission",
            "The OpenDesign web submission is unavailable",
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactStoreError(
            "artifact_missing",
            "artifact_submission",
            "The OpenDesign web submission is unavailable",
        )
    root = Path(tempfile.mkdtemp(prefix="maverick-opendesign-submission-", dir="/var/tmp"))
    root.chmod(0o755)
    submitted = root / "candidate"
    try:
        _copy_readable_submission(source, submitted)
        yield submitted
    finally:
        _make_owner_writable(root)
        shutil.rmtree(root, ignore_errors=True)


def _copy_readable_submission(source: Path, destination: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        _copy_readable_submission_directory(
            descriptor,
            destination,
            source_mode=stat.S_IMODE(os.fstat(descriptor).st_mode),
        )
    finally:
        os.close(descriptor)


def _copy_readable_submission_directory(
    source_descriptor: int,
    destination: Path,
    *,
    source_mode: int,
) -> None:
    if source_mode & 0o222 or source_mode & 0o005 != 0o005:
        raise ArtifactStoreError(
            "artifact_permissions_invalid",
            "artifact_submission",
            "The OpenDesign web submission is not sealed and authority-readable",
        )
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    for name in sorted(os.listdir(source_descriptor)):
        if name in {".", ".."} or "/" in name or "\x00" in name:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_submission",
                "The OpenDesign web submission contains an unsafe entry",
            )
        metadata = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        target = destination / name
        if stat.S_ISDIR(metadata.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_descriptor,
            )
            try:
                _copy_readable_submission_directory(
                    child,
                    target,
                    source_mode=stat.S_IMODE(metadata.st_mode),
                )
            finally:
                os.close(child)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_submission",
                "The OpenDesign web submission contains an unsafe entry",
            )
        source_file = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=source_descriptor,
        )
        try:
            observed = os.fstat(source_file)
            if not stat.S_ISREG(observed.st_mode) or (
                observed.st_dev,
                observed.st_ino,
            ) != (metadata.st_dev, metadata.st_ino):
                raise ArtifactStoreError(
                    "artifact_integrity_mismatch",
                    "artifact_submission",
                    "The OpenDesign web submission changed during handoff",
                )
            mode = stat.S_IMODE(metadata.st_mode)
            if mode & 0o222 or not mode & 0o004:
                raise ArtifactStoreError(
                    "artifact_permissions_invalid",
                    "artifact_submission",
                    "The OpenDesign web submission is not sealed and authority-readable",
                )
            target_descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                mode,
            )
            try:
                while True:
                    chunk = os.read(source_file, 1024 * 1024)
                    if not chunk:
                        break
                    remaining = memoryview(chunk)
                    while remaining:
                        written = os.write(target_descriptor, remaining)
                        if written <= 0:
                            raise OSError("short artifact submission write")
                        remaining = remaining[written:]
                os.fsync(target_descriptor)
            finally:
                os.close(target_descriptor)
            target.chmod(mode)
        finally:
            os.close(source_file)
    destination.chmod(source_mode)


def _validated_authority_command(repository: Path) -> Path:
    configured = os.environ.get(AUTHORITY_COMMAND_ENV, "").strip()
    if not configured:
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority command is not configured",
        )
    command = Path(configured)
    if not command.is_absolute():
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority command is invalid",
        )
    try:
        metadata = command.lstat()
        resolved = command.resolve(strict=True)
        resolved_metadata = resolved.stat()
    except OSError as error:
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority command is unavailable",
        ) from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(resolved_metadata.st_mode)
        or resolved_metadata.st_uid != 0
        or resolved_metadata.st_mode & 0o022
        or resolved == repository
        or repository in resolved.parents
    ):
        raise ArtifactStoreError(
            "artifact_authority_unavailable",
            "artifact_authority",
            "The platform artifact authority command is not root-protected",
        )
    for parent in resolved.parents:
        parent_metadata = parent.lstat()
        if (
            stat.S_ISLNK(parent_metadata.st_mode)
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != 0
            or parent_metadata.st_mode & 0o022
        ):
            raise ArtifactStoreError(
                "artifact_authority_unavailable",
                "artifact_authority",
                "The platform artifact authority command path is not root-protected",
            )
        if parent == Path("/"):
            break
    return resolved


def _read_selection() -> dict[str, Any]:
    try:
        payload = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactStoreError("runtime_binding_invalid", "release_selection", "Release selection is invalid") from error
    expected = {
        "schema_version",
        "active_web_overlay_sha256",
        "rollback_runtime_artifact_sha256",
        "rollback_web_overlay_sha256",
        "runtime_source_catalog_sha256",
        "quarantine_retention_days",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema_version") != "3":
        raise ArtifactStoreError("runtime_binding_invalid", "release_selection", "Release selection schema is invalid")
    if any(
        not is_sha256(payload.get(field))
        for field in (
            "active_web_overlay_sha256",
            "rollback_runtime_artifact_sha256",
            "rollback_web_overlay_sha256",
            "runtime_source_catalog_sha256",
        )
    ):
        raise ArtifactStoreError("runtime_binding_invalid", "release_selection", "Release selection digest is invalid")
    if payload["active_web_overlay_sha256"] == payload["rollback_web_overlay_sha256"]:
        raise ArtifactStoreError("runtime_binding_invalid", "release_selection", "Release overlays must be distinct")
    try:
        catalog_sha256 = sha256_file(RUNTIME_SOURCE_CATALOG_PATH)
    except ArtifactError as error:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "runtime_source_catalog",
            "The runtime source catalog is unavailable",
        ) from error
    if payload["runtime_source_catalog_sha256"] != catalog_sha256:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "runtime_source_catalog",
            "The release selection does not bind the runtime source catalog",
        )
    retention = payload["quarantine_retention_days"]
    if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= 365:
        raise ArtifactStoreError("runtime_binding_invalid", "release_selection", "Release retention is invalid")
    return payload


def _garbage_collect(store: OpenDesignArtifactStore, *, required: RequiredArtifacts) -> dict[str, Any]:
    staging_recovery = store.recover_orphaned_staging()
    keep_runtime = set(_runtime_references(required))
    keep_web = set(required.web_overlays)
    marked: list[str] = []
    for kind, keep in (("runtime", keep_runtime), ("web", keep_web)):
        for candidate in (store.root / kind).iterdir():
            if candidate.name in keep or candidate.is_symlink() or not candidate.is_dir():
                continue
            marker = store.root / "quarantine" / kind / f"gc-{candidate.name}.{uuid4().hex[:8]}"
            os.rename(candidate, marker)
            marked.append(f"{kind}:{candidate.name}")
    _purge_expired_quarantine(store.root, retention_days=int(_read_selection()["quarantine_retention_days"]))
    return {
        "marked_for_gc": sorted(marked),
        "staging_recovery": staging_recovery,
    }


def _purge_expired_quarantine(root: Path, *, retention_days: int) -> None:
    cutoff = datetime.now(tz=UTC) - timedelta(days=max(1, retention_days))
    for kind in ("runtime", "web", "staging"):
        for candidate in (root / "quarantine" / kind).iterdir():
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
            if modified >= cutoff:
                continue
            _make_owner_writable(candidate)
            shutil.rmtree(candidate)


def _prewarm(repository: Path, *, workspace_id: str) -> dict[str, Any]:
    readiness = request_sidecar_control(
        repository,
        operation="prewarm",
        workspace_id=workspace_id,
        app_id=APP_ID,
        timeout_seconds=15,
    )
    if readiness.get("ready") is not True:
        raise ArtifactStoreError("daemon_ready_timeout", "prewarm", "Governed sidecar prewarm did not become ready")
    return {"schema_version": "1", "operation": "prewarm", "status": "ready", "readiness": readiness}


def _diagnostics(repository: Path, *, data_root: Path) -> dict[str, Any]:
    del repository
    path = data_root / "opendesign" / "launcher-status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "1", "operation": "diagnostics", "status": "not_started"}
    allowed = {key: payload.get(key) for key in ("schema_version", "startup_id", "phase", "health", "timings_ms", "last_failure")}
    return {"operation": "diagnostics", "status": "available", **allowed}


def _append_audit(root: Path, *, operation: str, status: str, duration_ms: float, error_code: str | None, auto: bool) -> None:
    audit_root = root / "audit"
    _ensure_readable_audit_root(audit_root)
    path = audit_root / "events.jsonl"
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ArtifactStoreError("artifact_permissions_invalid", "audit", "Artifact audit log is unsafe")
    payload = {
        "event_id": uuid4().hex,
        "timestamp": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "operation": operation,
        "status": status,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "auto": auto,
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    try:
        os.write(descriptor, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o640)


def _make_owner_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | stat.S_IWUSR)


def _unique(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _runtime_references(required: RequiredArtifacts) -> list[str]:
    return _unique(
        (
            required.current_runtime,
            required.active_runtime,
            required.rollback_runtime,
            *required.required_runtime_artifacts,
            *required.optional_runtime,
        )
    )


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 3)
