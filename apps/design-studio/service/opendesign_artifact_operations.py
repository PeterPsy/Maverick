"""Governed OpenDesign artifact status, audit, repair, bootstrap, and diagnostics."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Any, Iterator
from uuid import uuid4

from core.apps.artifact_mounts import create_artifact_namespace, platform_artifact_store_root
from core.api.sidecar_control import request_sidecar_control
from core.shared.repository import discover_repository_root
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
SELECTION_PATH = SERVICE_ROOT / "opendesign_release_selection.json"
TRUST_CONTRACT_PATH = SERVICE_ROOT / "opendesign_web_trust.json"
APP_ID = "design-studio"
ARTIFACT_ID = "opendesign"


@dataclass(frozen=True)
class RequiredArtifacts:
    current_runtime: str
    active_runtime: str
    rollback_runtime: str
    active_web: str
    optional_runtime: tuple[str, ...]
    web_overlays: tuple[str, ...]
    fresh_web_overlay: str


def run_artifact_operation(
    operation: str,
    *,
    data_root: Path,
    workspace_id: str = "default",
    repository_root: Path | None = None,
    auto: bool = False,
    audit_workers: int | None = None,
) -> dict[str, Any]:
    """Run one bounded operator action and return redaction-safe JSON."""
    repository = discover_repository_root(start_path=repository_root or SERVICE_ROOT)
    started = time.monotonic()
    if operation not in {"status", "verify", "repair", "provision", "prewarm", "diagnostics", "gc"}:
        raise ArtifactStoreError("runtime_binding_invalid", "artifact_operation", "Unsupported artifact operation")
    if operation == "prewarm":
        return _prewarm(repository, workspace_id=workspace_id)
    if operation == "diagnostics":
        return _diagnostics(repository, data_root=data_root)

    namespace = _namespace(repository, create=operation in {"repair", "provision", "gc"})
    store = OpenDesignArtifactStore(namespace)
    staging_recovery = (
        store.recover_orphaned_staging()
        if operation in {"repair", "provision"}
        else None
    )
    runtime_sources = load_runtime_source_catalog()
    manifest = runtime_sources.by_role["current"].manifest
    required = _required_artifacts(data_root, manifest=manifest)
    _validate_required_runtime_sources(required, runtime_sources=runtime_sources)
    try:
        if operation in {"repair", "provision"}:
            with _repair_operation_lock(store):
                result = _repair(
                    store,
                    required=required,
                    runtime_sources=runtime_sources,
                    data_root=data_root,
                )
        elif operation == "verify":
            result = _verify(store, required=required, max_workers=audit_workers)
        elif operation == "gc":
            result = _garbage_collect(store, required=required)
        else:
            result = _status(store, required=required)
    except Exception as error:
        if operation != "status":
            _append_audit(
                store.root,
                operation=operation,
                status="failed",
                duration_ms=_elapsed_ms(started),
                error_code=getattr(error, "code", type(error).__name__),
                auto=auto,
            )
        raise
    if operation != "status":
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


def _repair(
    store: OpenDesignArtifactStore,
    *,
    required: RequiredArtifacts,
    runtime_sources: RuntimeSourceCatalog,
    data_root: Path,
) -> dict[str, Any]:
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
    required_runtime = {required.active_runtime, required.rollback_runtime}
    for digest in _unique((required.active_runtime, required.rollback_runtime, *required.optional_runtime)):
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
    runtime_candidates = _unique(
        (
            required.active_runtime,
            required.current_runtime,
            required.rollback_runtime,
            *required.optional_runtime,
        )
    )
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
        source = SERVICE_ROOT / "artifacts/open-design-web" / digest
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
    bootstrapped = _bootstrap_fresh_generation(
        data_root,
        runtime=runtime,
        web=store.fast_web_overlay(required.fresh_web_overlay, runtime_artifact_sha256=required.current_runtime),
    )
    return {
        "runtime_artifact_sha256": runtime.artifact_sha256,
        "runtime_repaired": runtime_repaired,
        "repaired_runtime_artifacts": repaired_runtime,
        "retained_runtime_artifacts": retained_runtime,
        "web_overlay_sha256": required.fresh_web_overlay,
        "repaired_web_overlays": repaired_web,
        "retained_web_overlays": retained_web,
        "data_generation_bootstrapped": bootstrapped,
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
        artifact_directory = source.artifact_directory(SERVICE_ROOT / "artifacts")
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
    runtime_states: dict[str, str] = {}
    for digest in _unique(
        (
            required.current_runtime,
            required.active_runtime,
            required.rollback_runtime,
            *required.optional_runtime,
        )
    ):
        try:
            store.fast_runtime(digest, file_manifest_sha256=None, opendesign_version="0.16.1", upstream_commit=None)
            runtime_states[digest] = "verified_fast"
        except ArtifactStoreError as error:
            runtime_states[digest] = error.code
    web_states: dict[str, str] = {}
    for digest in required.web_overlays:
        last_error: ArtifactStoreError | None = None
        for runtime_digest in _unique(
            (
                required.active_runtime,
                required.current_runtime,
                required.rollback_runtime,
                *required.optional_runtime,
            )
        ):
            try:
                store.fast_web_overlay(digest, runtime_artifact_sha256=runtime_digest)
                web_states[digest] = "verified_fast"
                break
            except ArtifactStoreError as error:
                last_error = error
        else:
            web_states[digest] = last_error.code if last_error is not None else "artifact_missing"
    try:
        store.fast_web_overlay(required.active_web, runtime_artifact_sha256=required.active_runtime)
        active_web_ready = True
    except ArtifactStoreError:
        active_web_ready = False
    operational = runtime_states.get(required.active_runtime) == "verified_fast" and active_web_ready
    retained = all(state == "verified_fast" for state in (*runtime_states.values(), *web_states.values()))
    return {
        "operational": operational,
        "retention_complete": retained,
        "runtime": runtime_states,
        "web": web_states,
    }


def _verify(
    store: OpenDesignArtifactStore,
    *,
    required: RequiredArtifacts,
    max_workers: int | None = None,
) -> dict[str, Any]:
    audited_runtime: list[str] = []
    for digest in _unique(
        (
            required.current_runtime,
            required.active_runtime,
            required.rollback_runtime,
            *required.optional_runtime,
        )
    ):
        try:
            store.full_audit("runtime", digest, max_workers=max_workers)
        except ArtifactStoreError:
            _mark_invalid(store, kind="runtime", digest=digest)
            if digest in {required.current_runtime, required.active_runtime, required.rollback_runtime}:
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
    path.chmod(0o640)


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
    control_path = data_root / "opendesign" / "control.json"
    if control_path.is_file() and not control_path.is_symlink():
        control = load_generation_control_metadata(control_path.parent)
        active_runtime = control.active.runtime_artifact_sha256
        active_web = control.active.web_overlay_sha256
        web.append(control.active.web_overlay_sha256)
        if control.previous_release is not None:
            optional_runtime.append(control.previous_release.runtime_artifact_sha256)
            web.append(control.previous_release.web_overlay_sha256)
        if control.previous_web is not None:
            optional_runtime.append(control.previous_web.runtime_artifact_sha256)
            web.append(control.previous_web.web_overlay_sha256)
        if control.previous_runtime is not None:
            optional_runtime.append(control.previous_runtime.runtime_artifact_sha256)
            web.append(control.previous_runtime.web_overlay_sha256)
    return RequiredArtifacts(
        current_runtime=current,
        active_runtime=active_runtime,
        rollback_runtime=rollback_runtime,
        active_web=active_web,
        optional_runtime=tuple(_unique(optional_runtime)),
        web_overlays=tuple(_unique(web)),
        fresh_web_overlay=str(release["active_web_overlay_sha256"]),
    )


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


def _namespace(repository: Path, *, create: bool) -> Path:
    if create:
        return create_artifact_namespace(repository_root=repository, app_id=APP_ID, artifact_id=ARTIFACT_ID)
    namespace = platform_artifact_store_root(repository) / APP_ID / ARTIFACT_ID
    if not namespace.is_dir() or namespace.is_symlink():
        raise ArtifactStoreError("artifact_missing", "status", "The protected OpenDesign store is unavailable")
    return namespace


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
    keep_runtime = set(
        (
            required.current_runtime,
            required.active_runtime,
            required.rollback_runtime,
            *required.optional_runtime,
        )
    )
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
    audit_root.mkdir(mode=0o750, exist_ok=True)
    audit_root.chmod(0o750)
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


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 3)
