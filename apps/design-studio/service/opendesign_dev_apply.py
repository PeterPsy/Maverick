"""App-owned incremental Design Studio development orchestrator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

from core.apps.artifact_mounts import (
    create_artifact_namespace,
    platform_artifact_store_root,
)
from core.api.sidecar_control import request_sidecar_control
from opendesign_artifact import read_bundle_manifest
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_dev_changeset import (
    DevApplyError,
    PATCH_SERIES_PATH,
    assert_changeset_unchanged as _assert_changeset_unchanged,
    changed_patch_series_components as _changed_patch_series_components,
    materialize_changeset,
    normalize_path as _normalize_path,
    resolve_changeset,
    resolve_commit as _resolve_commit,
)
from opendesign_runtime import protected_activation_inventory, verified_overlay_from_store
from opendesign_web_activation import activate_web_overlay, recover_web_activation
from opendesign_web_builder import build_dev_overlay, build_release_overlay


ACTION_ORDER = (
    "design_studio_frontend_tests",
    "design_studio_frontend_build",
    "design_studio_backend_tests",
    "opendesign_web_overlay",
    "opendesign_oci_pipeline",
    "app_hosting_core_tests",
    "changed_suite",
    "opendesign_e2e_quick",
    "opendesign_e2e_affected",
    "opendesign_e2e_release",
)

CONSERVATIVE_ACTIONS = {
    "design_studio_frontend_tests",
    "design_studio_frontend_build",
    "design_studio_backend_tests",
    "opendesign_web_overlay",
    "opendesign_oci_pipeline",
    "app_hosting_core_tests",
    "changed_suite",
    "opendesign_e2e_affected",
}
WEB_PATCH_COMPONENTS = {"web-build", "web-react"}


@dataclass(frozen=True)
class DiffClassification:
    changed_files: tuple[str, ...]
    categories: tuple[str, ...]
    actions: tuple[str, ...]
    conservative_elevation: bool
    unknown_files: tuple[str, ...]


class GateExecutionError(RuntimeError):
    """Bounded, redaction-safe failure for one isolated dev-apply gate."""

    def __init__(self, action: str, exit_code: int, *, stdout: str, stderr: str) -> None:
        super().__init__(f"gate {action} exited with status {exit_code}")
        self.code = f"{action}_failed"
        self.phase = action
        self.exit_code = exit_code
        self.diagnostic = _redacted_gate_diagnostic(stderr or stdout)


def classify_diff(
    paths: Iterable[str],
    *,
    profile: str = "dev",
    series_components: Iterable[str] | None = None,
) -> DiffClassification:
    """Classify a multi-file diff compositionally and fail upward for unknown paths."""
    if profile not in {"dev", "release"}:
        raise ValueError("profile must be dev or release")
    changed = tuple(sorted({_normalize_path(path) for path in paths if str(path).strip()}))
    categories: set[str] = set()
    actions: set[str] = set()
    unknown: list[str] = []
    resolved_series_components = (
        set(series_components)
        if series_components is not None
        else _infer_series_components_from_paths(changed)
    )
    for path in changed:
        if path == PATCH_SERIES_PATH:
            category, implied = _classify_series_components(resolved_series_components)
        else:
            category, implied = _classify_path(path)
        if category is None:
            unknown.append(path)
            continue
        categories.add(category)
        actions.update(implied)
    if unknown:
        categories.add("unknown")
        actions.update(CONSERVATIVE_ACTIONS)
    if "opendesign_e2e_affected" in actions:
        actions.discard("opendesign_e2e_quick")
    if actions:
        if profile == "release":
            actions.discard("opendesign_e2e_quick")
            actions.discard("opendesign_e2e_affected")
            actions.add("opendesign_e2e_release")
    return DiffClassification(
        changed_files=changed,
        categories=tuple(sorted(categories)),
        actions=tuple(action for action in ACTION_ORDER if action in actions),
        conservative_elevation=bool(unknown),
        unknown_files=tuple(unknown),
    )


def _infer_series_components_from_paths(paths: tuple[str, ...]) -> set[str]:
    components: set[str] = set()
    for path in paths:
        if path.endswith("patches/0001-maverick-runtime-boundary.patch"):
            components.add("runtime")
        elif path.endswith("patches/0002-maverick-web-build.patch"):
            components.add("web-build")
        elif path.endswith("patches/0003-maverick-web-react.patch"):
            components.add("web-react")
    return components or {"unknown"}


def _classify_series_components(components: set[str]) -> tuple[str, set[str]]:
    actions: set[str] = set()
    if components & WEB_PATCH_COMPONENTS:
        actions.update({"opendesign_web_overlay", "opendesign_e2e_affected"})
    if components - WEB_PATCH_COMPONENTS:
        actions.update({"opendesign_oci_pipeline", "opendesign_e2e_affected"})
    if not actions:
        actions.add("design_studio_backend_tests")
    category = "opendesign-web-series" if components <= WEB_PATCH_COMPONENTS else "opendesign-patch-series"
    return category, actions


def apply_incremental(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute the selected gates and return bounded JSON evidence."""
    repo_root = _repo_root(arguments)
    profile = str(arguments.get("profile") or "dev")
    if profile not in {"dev", "release"}:
        raise DevApplyError("profile must be dev or release", report={})
    changeset = resolve_changeset(arguments, repo_root=repo_root)
    series_components = _changed_patch_series_components(changeset, repo_root=repo_root)
    classification = classify_diff(
        changeset.changed_files,
        profile=profile,
        series_components=series_components,
    )
    report: dict[str, Any] = {
        "schema_version": "1",
        "app_id": "design-studio",
        "profile": profile,
        "changeset": asdict(changeset),
        "classification": asdict(classification),
        "execution": {
            "isolated_checkout": True,
            "base_commit_sha": changeset.head_sha or _resolve_commit(repo_root, "HEAD"),
        },
        "actions": [],
        "digests": {},
        "cache": {},
        "readiness": {},
        "rollback": {"performed": False},
        "change_to_live": None,
        "duration_seconds": 0.0,
        "ok": False,
    }
    started = time.monotonic()
    dry_run = bool(arguments.get("dry_run", False))
    persistent_cache_root = _cache_root(arguments, repo_root)
    try:
        with materialize_changeset(repo_root, changeset) as execution_root:
            for action in classification.actions:
                action_started = time.monotonic()
                if dry_run:
                    result: dict[str, Any] = {"status": "planned"}
                elif action == "opendesign_web_overlay":
                    result = _build_and_activate_overlay(
                        payload,
                        arguments,
                        repo_root=execution_root,
                        publish_repo_root=repo_root,
                        cache_root=persistent_cache_root,
                        release=profile == "release",
                    )
                    report["digests"].update(result.pop("digests"))
                    report["cache"] = result.pop("cache")
                    report["readiness"] = result.pop("readiness")
                    report["rollback"] = result.pop("rollback")
                    report["change_to_live"] = result.pop("change_to_live")
                else:
                    result = _run_gate(
                        action,
                        arguments,
                        repo_root=execution_root,
                        publish_repo_root=repo_root,
                        changed_files=changeset.changed_files,
                        web_overlay_sha256=report["digests"].get("web_overlay_sha256"),
                        cache_root=persistent_cache_root,
                    )
                report["actions"].append(
                    {
                        "name": action,
                        "duration_seconds": round(time.monotonic() - action_started, 6),
                        **result,
                    }
                )
        _assert_changeset_unchanged(changeset, repo_root=repo_root)
        report["ok"] = True
        return report
    except Exception as error:
        if not dry_run and _candidate_overlay_was_activated(report):
            try:
                report["rollback"] = _rollback_after_post_activation_failure(
                    payload,
                    arguments,
                    repo_root=repo_root,
                    previous_web_overlay_sha256=str(
                        report["change_to_live"]["previous_web_overlay_sha256"]
                    ),
                )
            except Exception as rollback_error:
                report["rollback"] = {
                    "performed": False,
                    "status": "failed",
                    "reason": "post_activation_gate_failed",
                    "error_code": type(rollback_error).__name__,
                }
        failure = {
            "name": classification.actions[len(report["actions"])]
            if len(report["actions"]) < len(classification.actions)
            else "unknown",
            "status": "failed",
            "error_code": getattr(error, "code", type(error).__name__),
            "phase": getattr(error, "phase", "dev_apply"),
        }
        if isinstance(getattr(error, "exit_code", None), int):
            failure["exit_code"] = error.exit_code
        if isinstance(getattr(error, "diagnostic", None), str) and error.diagnostic:
            failure["diagnostic"] = error.diagnostic
        report["actions"].append(failure)
        raise DevApplyError(
            f"Design Studio incremental apply failed: {failure['error_code']}",
            report=report,
        ) from error
    finally:
        report["duration_seconds"] = round(time.monotonic() - started, 6)


def _classify_path(path: str) -> tuple[str | None, set[str]]:
    if path.startswith("apps/design-studio/frontend/") or path in {
        "apps/design-studio/package.json",
        "apps/design-studio/package-lock.json",
        "apps/design-studio/tsconfig.json",
        "apps/design-studio/vite.config.ts",
    }:
        return "design-studio-wrapper", {
            "design_studio_frontend_tests",
            "design_studio_frontend_build",
            "opendesign_e2e_quick",
        }
    if path.startswith(("apps/design-studio/backend/", "apps/design-studio/mcp/", "apps/design-studio/cli/")):
        return "design-studio-backend", {
            "design_studio_backend_tests",
            "opendesign_e2e_affected",
        }
    if path.endswith(("patches/0002-maverick-web-build.patch", "patches/0003-maverick-web-react.patch")):
        return "opendesign-web", {
            "opendesign_web_overlay",
            "opendesign_e2e_affected",
        }
    if path in {
        "apps/design-studio/README.md",
        "apps/design-studio/service/README.md",
        "apps/design-studio/skills/design-studio-ops/SKILL.md",
    } or path.startswith("apps/design-studio/service/") and path.endswith((".md", ".txt")):
        return "design-studio-documentation", set()
    if path.startswith("apps/design-studio/tests/"):
        return "design-studio-tests", {"design_studio_backend_tests"}
    if path.startswith("apps/design-studio/service/"):
        return _classify_service_path(path)
    if path == "apps/design-studio/app_contract.json":
        return "core-app-contract", {
            "app_hosting_core_tests",
            "opendesign_e2e_affected",
        }
    if path.startswith(("core/apps/", "core/api/sidecar", "tests/unit/app_hosting/", "tests/integration/app_hosting/")):
        return "core-app-hosting", {
            "app_hosting_core_tests",
            "opendesign_e2e_affected",
        }
    if path.startswith(("core/", "tests/")) or path == "scripts/test_suite.py":
        return "repository-tests", {"changed_suite"}
    if path.startswith("apps/"):
        return "other-app", {"changed_suite"}
    if path.startswith(("docs/", "scripts/")) or path in {
        ".gitignore",
        "AGENTS.md",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
    }:
        return "repository-support", set()
    return None, set()


def _classify_service_path(path: str) -> tuple[str, set[str]]:
    filename = PurePosixPath(path).name
    if filename.startswith("opendesign_web_") or filename in {
        "aggregate_opendesign_release_evidence.py",
        "benchmark_opendesign_change_to_live.py",
        "opendesign_dev_apply.py",
    }:
        return "opendesign-web-tooling", {"design_studio_backend_tests"}
    if filename.endswith("_acceptance_0_16_1.json") or filename in {
        "opendesign_change_to_live_benchmark_0_16_1.json",
        "opendesign_web_trust.json",
    }:
        return "opendesign-release-evidence", set()
    return "opendesign-runtime-supply-chain", {
        "opendesign_oci_pipeline",
        "opendesign_e2e_affected",
    }


def _run_gate(
    action: str,
    arguments: dict[str, Any],
    *,
    repo_root: Path,
    publish_repo_root: Path | None = None,
    changed_files: tuple[str, ...],
    web_overlay_sha256: str | None = None,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    environment: dict[str, str] | None = None
    if action == "design_studio_frontend_tests":
        command = ["npm", "test"]
        cwd = repo_root / "apps/design-studio"
    elif action == "design_studio_frontend_build":
        command = ["npm", "run", "build"]
        cwd = repo_root / "apps/design-studio"
    elif action == "design_studio_backend_tests":
        command = [sys.executable, "scripts/test_suite.py", "--level", "app-backend", "--app", "design-studio"]
        cwd = repo_root
    elif action == "app_hosting_core_tests":
        command = [sys.executable, "scripts/test_suite.py", "--area", "app-hosting"]
        cwd = repo_root
    elif action == "changed_suite":
        command = [sys.executable, "scripts/test_suite.py", "--changed"]
        for path in changed_files:
            command.extend(("--changed-path", path))
        cwd = repo_root
    elif action.startswith("opendesign_e2e_"):
        e2e_profile = action.removeprefix("opendesign_e2e_")
        command = ["npm", "run", f"test:e2e:{e2e_profile}", "--"]
        for path in changed_files:
            command.extend(("--changed-file", path))
        if web_overlay_sha256:
            command.extend(("--web-overlay-sha256", web_overlay_sha256))
        cwd = repo_root / "apps/design-studio"
        environment = _e2e_environment(
            arguments,
            execution_repo_root=repo_root,
            publish_repo_root=publish_repo_root or repo_root,
        )
    elif action == "opendesign_oci_pipeline":
        source = _required_path(arguments, "source_repository")
        signing_key = _required_path(arguments, "runtime_signing_key")
        command = [
            sys.executable,
            "apps/design-studio/service/import_opendesign_oci.py",
            "--source-repository",
            str(source),
            "--signing-key",
            str(signing_key),
            "--output-directory",
            str((publish_repo_root or repo_root) / "apps/design-studio/service/artifacts"),
            "--work-parent",
            str((cache_root or _cache_root(arguments, publish_repo_root or repo_root)) / "work"),
            "--pnpm-store",
            str((cache_root or _cache_root(arguments, publish_repo_root or repo_root)) / "pnpm-store"),
        ]
        cwd = repo_root
    else:
        raise RuntimeError(f"unsupported dev apply gate: {action}")
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        **({"env": environment} if environment is not None else {}),
    )
    if completed.returncode != 0:
        raise GateExecutionError(
            action,
            completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    result: dict[str, Any] = {"status": "passed", "exit_code": completed.returncode}
    if completed.stdout.strip().startswith("{"):
        try:
            result["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            pass
    return result


def _redacted_gate_diagnostic(value: str) -> str:
    """Return one useful gate line without paths, credentials, or payloads."""
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    candidates = [line for line in lines if "error" in line.lower() or "failed" in line.lower()]
    diagnostic = (candidates[-1] if candidates else lines[-1])[:512]
    lowered = diagnostic.lower()
    if any(
        marker in lowered
        for marker in ("authorization", "bearer", "cookie", "password", "secret", "api_key", "api-key")
    ):
        return "[redacted gate diagnostic]"
    diagnostic = re.sub(r"(?<![A-Za-z0-9_.-])/(?:[^\s:'\"`]+)", "<path>", diagnostic)
    return diagnostic[:240]


def _build_and_activate_overlay(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    repo_root: Path,
    publish_repo_root: Path | None = None,
    cache_root: Path | None = None,
    release: bool,
) -> dict[str, Any]:
    service_root = repo_root / "apps/design-studio/service"
    source_repository = _required_path(arguments, "source_repository")
    signing_key = _required_path(arguments, "web_signing_key")
    cache_root = cache_root or _cache_root(arguments, publish_repo_root or repo_root)
    work_parent = _work_parent(arguments)
    for child in (cache_root, work_parent):
        child.mkdir(parents=True, exist_ok=True)
    registry_root = cache_root / "built-overlays"
    registry_root.mkdir(parents=True, exist_ok=True)
    manifest = read_bundle_manifest(service_root / "opendesign_bundle.json")
    builder = build_release_overlay if release else build_dev_overlay
    build_started = time.monotonic()
    result = builder(
        source_repository,
        manifest=manifest,
        service_root=service_root,
        cache_root=cache_root,
        registry_root=registry_root,
        signing_key=signing_key,
        trust_contract=service_root / "opendesign_web_trust.json",
        work_parent=work_parent,
        runtime_session_id=str(payload.get("runtime_session_id") or "") or None,
    )
    namespace = create_artifact_namespace(
        repository_root=publish_repo_root or repo_root,
        app_id="design-studio",
        artifact_id="opendesign",
    )
    store = OpenDesignArtifactStore(namespace)
    stored_candidate = store.publish_web_overlay(
        result.overlay.path,
        web_overlay_sha256=result.overlay.web_overlay_sha256,
        trust_contract=service_root / "opendesign_web_trust.json",
    )
    build_duration = round(time.monotonic() - build_started, 6)
    generation_root = Path(str(payload.get("data_root") or "")) / "opendesign"
    control, verified_artifacts, overlays = protected_activation_inventory(
        store=store,
        generation_root=generation_root,
    )
    overlays[stored_candidate.artifact_sha256] = verified_overlay_from_store(stored_candidate)
    recover_web_activation(
        generation_root,
        verified_artifacts=verified_artifacts,
        verified_overlays=overlays,
        restart_sidecars=lambda: _restart_sidecars(
            arguments,
            repo_root=publish_repo_root or repo_root,
        ),
    )
    control, verified_artifacts, retained_overlays = protected_activation_inventory(
        store=store,
        generation_root=generation_root,
    )
    overlays.update(retained_overlays)
    previous_web_overlay_sha256 = control.active.web_overlay_sha256
    activation_started = time.monotonic()
    if control.active.web_overlay_sha256 == result.overlay.web_overlay_sha256:
        readiness = {
            "ready": True,
            "service_count": 1,
            "restart_skipped": True,
            "browser_remount_event_emitted": False,
        }
        rollback = {"performed": False}
    else:
        activation_id = f"web_dev_{result.overlay.web_overlay_sha256[:16]}"
        outcome = activate_web_overlay(
            generation_root,
            target_web_overlay_sha256=result.overlay.web_overlay_sha256,
            web_activation_id=activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=overlays,
            restart_sidecars=lambda: _restart_sidecars(
                arguments,
                repo_root=publish_repo_root or repo_root,
            ),
        )
        if not outcome.activated or outcome.rolled_back:
            raise RuntimeError("web overlay candidate did not remain active after readiness")
        readiness = outcome.readiness
        rollback = {"performed": outcome.rolled_back, "web_activation_id": activation_id}
    activation_duration = round(time.monotonic() - activation_started, 6)
    metrics = [asdict(metric) for metric in result.metrics]
    source_build_cache_hit = all(metric.source_build_cache_hit for metric in result.metrics)
    return {
        "status": "passed",
        "derivations": result.derivations,
        "reproducible": result.reproducible,
        "digests": {
            "runtime_artifact_sha256": control.active.runtime_artifact_sha256,
            "web_overlay_sha256": result.overlay.web_overlay_sha256,
        },
        "cache": {
            "materialization_hit": result.cache_hit,
            "derivations": metrics,
        },
        "readiness": readiness,
        "rollback": rollback,
        "change_to_live": {
            "previous_web_overlay_sha256": previous_web_overlay_sha256,
            "candidate_web_overlay_sha256": result.overlay.web_overlay_sha256,
            "overlay_changed": previous_web_overlay_sha256 != result.overlay.web_overlay_sha256,
            "activated": previous_web_overlay_sha256 != result.overlay.web_overlay_sha256,
            "source_build_cache_hit": source_build_cache_hit,
            "build_duration_seconds": build_duration,
            "activation_restart_readiness_seconds": activation_duration,
            "duration_seconds": round(build_duration + activation_duration, 6),
            "browser_remount_event_emitted": readiness.get("browser_remount_event_emitted") is True,
        },
    }


def _restart_sidecars(arguments: dict[str, Any], *, repo_root: Path) -> dict[str, object]:
    payload = request_sidecar_control(
        repo_root,
        operation="restart",
        workspace_id=str(arguments.get("workspace_id") or "default"),
        app_id="design-studio",
        timeout_seconds=15,
    )
    readiness = payload.get("readiness") if isinstance(payload, dict) else None
    if not isinstance(readiness, dict) or readiness.get("ready") is not True:
        raise RuntimeError("app sidecar restart readiness failed")
    event = payload.get("event") if isinstance(payload, dict) else None
    browser_remount_event_emitted = (
        isinstance(event, dict)
        and event.get("type") == "maverick.app.runtime-changed"
        and event.get("owner_app_id") == "design-studio"
        and event.get("resource") == "runtime/frontend"
    )
    return {**readiness, "browser_remount_event_emitted": browser_remount_event_emitted}


def _candidate_overlay_was_activated(report: dict[str, Any]) -> bool:
    change = report.get("change_to_live")
    return (
        isinstance(change, dict)
        and change.get("activated") is True
        and change.get("previous_web_overlay_sha256") != change.get("candidate_web_overlay_sha256")
    )


def _rollback_after_post_activation_failure(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    repo_root: Path,
    previous_web_overlay_sha256: str,
) -> dict[str, Any]:
    generation_root = Path(str(payload.get("data_root") or "")) / "opendesign"
    store = OpenDesignArtifactStore(
        platform_artifact_store_root(repo_root) / "design-studio" / "opendesign"
    )
    control, verified_artifacts, overlays = protected_activation_inventory(
        store=store,
        generation_root=generation_root,
    )
    if control.active.web_overlay_sha256 == previous_web_overlay_sha256:
        return {
            "performed": False,
            "status": "already_restored",
            "reason": "post_activation_gate_failed",
        }
    nonce = hashlib.sha256(str(time.time_ns()).encode("ascii")).hexdigest()[:16]
    activation_id = f"web_gate_rollback_{nonce}"
    outcome = activate_web_overlay(
        generation_root,
        target_web_overlay_sha256=previous_web_overlay_sha256,
        web_activation_id=activation_id,
        verified_artifacts=verified_artifacts,
        verified_overlays=overlays,
        restart_sidecars=lambda: _restart_sidecars(arguments, repo_root=repo_root),
    )
    if not outcome.activated or outcome.rolled_back:
        raise RuntimeError("previous web overlay did not become ready during automatic rollback")
    return {
        "performed": True,
        "status": "passed",
        "reason": "post_activation_gate_failed",
        "web_activation_id": activation_id,
        "restored_web_overlay_sha256": previous_web_overlay_sha256,
        "readiness": outcome.readiness,
    }


def _repo_root(arguments: dict[str, Any]) -> Path:
    value = arguments.get("repo_root")
    root = Path(str(value)).resolve() if value else Path(__file__).resolve().parents[3]
    if not (root / "AGENTS.md").is_file() or not (root / "apps/design-studio").is_dir():
        raise DevApplyError("repo_root is not the Maverick v3 repository", report={})
    return root


def _cache_root(arguments: dict[str, Any], repo_root: Path) -> Path:
    raw = arguments.get("cache_root") or os.environ.get("MAVERICK_OPENDESIGN_WEB_CACHE")
    return Path(str(raw)).resolve() if raw else repo_root / "tmp/opendesign-web-cache"


def _e2e_environment(
    arguments: dict[str, Any],
    *,
    execution_repo_root: Path,
    publish_repo_root: Path,
) -> dict[str, str]:
    playwright_package = (
        execution_repo_root / "apps/design-studio/node_modules/playwright/package.json"
    )
    if not playwright_package.is_file():
        raise RuntimeError("isolated E2E checkout is missing the verified Playwright package")

    raw_python = (
        arguments.get("e2e_python")
        or os.environ.get("MAVERICK_OPENDESIGN_E2E_PYTHON")
        or publish_repo_root / ".venv/bin/python"
    )
    python = Path(str(raw_python)).absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError("OpenDesign E2E Python runtime is unavailable")

    default_browsers = _publishing_user_home(publish_repo_root) / ".cache/ms-playwright"
    raw_browsers = (
        arguments.get("playwright_browsers_path")
        or os.environ.get("MAVERICK_PLAYWRIGHT_BROWSERS_PATH")
        or os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        or default_browsers
    )
    browsers = Path(str(raw_browsers)).absolute()
    if not browsers.is_dir():
        raise RuntimeError("OpenDesign E2E Playwright browser cache is unavailable")

    environment = dict(os.environ)
    environment["MAVERICK_OPENDESIGN_E2E_PYTHON"] = str(python)
    environment["MAVERICK_PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    environment["MAVERICK_APP_ARTIFACT_STORE_ROOT"] = str(
        platform_artifact_store_root(publish_repo_root)
    )
    return environment


def _publishing_user_home(publish_repo_root: Path) -> Path:
    try:
        repository_owner = pwd.getpwuid(publish_repo_root.stat().st_uid)
    except (KeyError, OSError) as error:
        raise RuntimeError("OpenDesign E2E publishing repository owner is unavailable") from error
    home = Path(repository_owner.pw_dir)
    if not home.is_absolute():
        raise RuntimeError("OpenDesign E2E publishing repository owner has no absolute home")
    return home


def _work_parent(arguments: dict[str, Any]) -> Path:
    raw = arguments.get("work_parent") or os.environ.get("MAVERICK_OPENDESIGN_WEB_WORK")
    path = Path(str(raw)).resolve() if raw else Path(tempfile.gettempdir()) / "mav-odw"
    if len(str(path)) > 72:
        raise DevApplyError("work_parent is too long for OpenDesign build Unix sockets", report={})
    return path

def _required_path(arguments: dict[str, Any], key: str) -> Path:
    value = arguments.get(key) or os.environ.get(f"MAVERICK_{key.upper()}")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{key} is required for this change profile")
    path = Path(value).resolve()
    if not path.exists() or path.is_symlink():
        raise RuntimeError(f"{key} must identify a real path")
    return path
