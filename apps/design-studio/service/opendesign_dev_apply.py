"""App-owned incremental Design Studio development orchestrator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

from opendesign_artifact import read_bundle_manifest
from opendesign_generation_control import load_generation_control
from opendesign_materialization import discover_verified_bundles
from opendesign_web_activation import activate_web_overlay
from opendesign_web_builder import build_dev_overlay, build_release_overlay
from opendesign_web_overlay import discover_verified_overlays


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


class DevApplyError(RuntimeError):
    """Raised when an incremental apply action fails."""

    def __init__(self, message: str, *, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class DiffClassification:
    changed_files: tuple[str, ...]
    categories: tuple[str, ...]
    actions: tuple[str, ...]
    conservative_elevation: bool
    unknown_files: tuple[str, ...]


@dataclass(frozen=True)
class ChangeSet:
    source: str
    changed_files: tuple[str, ...]
    base_sha: str | None
    head_sha: str | None
    path_sha256: dict[str, str | None]


def classify_diff(paths: Iterable[str], *, profile: str = "dev") -> DiffClassification:
    """Classify a multi-file diff compositionally and fail upward for unknown paths."""
    if profile not in {"dev", "release"}:
        raise ValueError("profile must be dev or release")
    changed = tuple(sorted({_normalize_path(path) for path in paths if str(path).strip()}))
    categories: set[str] = set()
    actions: set[str] = set()
    unknown: list[str] = []
    for path in changed:
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


def apply_incremental(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute the selected gates and return bounded JSON evidence."""
    repo_root = _repo_root(arguments)
    profile = str(arguments.get("profile") or "dev")
    if profile not in {"dev", "release"}:
        raise DevApplyError("profile must be dev or release", report={})
    changeset = resolve_changeset(arguments, repo_root=repo_root)
    classification = classify_diff(changeset.changed_files, profile=profile)
    report: dict[str, Any] = {
        "schema_version": "1",
        "app_id": "design-studio",
        "profile": profile,
        "changeset": asdict(changeset),
        "classification": asdict(classification),
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
    try:
        for action in classification.actions:
            action_started = time.monotonic()
            if dry_run:
                result: dict[str, Any] = {"status": "planned"}
            elif action == "opendesign_web_overlay":
                result = _build_and_activate_overlay(
                    payload,
                    arguments,
                    repo_root=repo_root,
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
                    repo_root=repo_root,
                    changed_files=changeset.changed_files,
                    web_overlay_sha256=report["digests"].get("web_overlay_sha256"),
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
        report["actions"].append(
            {
                "name": classification.actions[len(report["actions"])]
                if len(report["actions"]) < len(classification.actions)
                else "unknown",
                "status": "failed",
                "error_code": type(error).__name__,
            }
        )
        raise DevApplyError(
            f"Design Studio incremental apply failed: {type(error).__name__}",
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
    changed_files: tuple[str, ...],
    web_overlay_sha256: str | None = None,
) -> dict[str, Any]:
    if action == "design_studio_frontend_tests":
        command = ["npm", "test"]
        cwd = repo_root / "apps/design-studio"
    elif action == "design_studio_frontend_build":
        command = _maverick_command(
            "app",
            "design-studio",
            "frontend",
            "build",
            "--workspace",
            str(arguments.get("workspace_id") or "default"),
            "--json",
        )
        cwd = repo_root
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
            str(repo_root / "apps/design-studio/service/artifacts"),
            "--work-parent",
            str(_cache_root(arguments, repo_root) / "work"),
            "--pnpm-store",
            str(_cache_root(arguments, repo_root) / "pnpm-store"),
        ]
        cwd = repo_root
    else:
        raise RuntimeError(f"unsupported dev apply gate: {action}")
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"gate {action} exited with status {completed.returncode}")
    result: dict[str, Any] = {"status": "passed", "exit_code": completed.returncode}
    if completed.stdout.strip().startswith("{"):
        try:
            result["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            pass
    return result


def _build_and_activate_overlay(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    repo_root: Path,
    release: bool,
) -> dict[str, Any]:
    service_root = repo_root / "apps/design-studio/service"
    source_repository = _required_path(arguments, "source_repository")
    signing_key = _required_path(arguments, "web_signing_key")
    cache_root = _cache_root(arguments, repo_root)
    work_parent = _work_parent(arguments)
    for child in (cache_root, work_parent):
        child.mkdir(parents=True, exist_ok=True)
    registry_root = service_root / "vendor/open-design-web"
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
    build_duration = round(time.monotonic() - build_started, 6)
    generation_root = Path(str(payload.get("data_root") or "")) / "opendesign"
    bundles = discover_verified_bundles(service_root / "vendor/open-design")
    verified_artifacts = {digest: bundle.opendesign_version for digest, bundle in bundles.items()}
    overlays = discover_verified_overlays(
        registry_root,
        trust_contract=service_root / "opendesign_web_trust.json",
    )
    control = load_generation_control(
        generation_root,
        verified_artifacts=verified_artifacts,
        verified_overlays=overlays,
    )
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
            restart_sidecars=lambda: _restart_sidecars(arguments, repo_root=repo_root),
        )
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
            "source_build_cache_hit": source_build_cache_hit,
            "build_duration_seconds": build_duration,
            "activation_restart_readiness_seconds": activation_duration,
            "duration_seconds": round(build_duration + activation_duration, 6),
            "browser_remount_event_emitted": readiness.get("browser_remount_event_emitted") is True,
        },
    }


def _restart_sidecars(arguments: dict[str, Any], *, repo_root: Path) -> dict[str, object]:
    command = _maverick_command(
        "core",
        "cli",
        "run",
        "app.design-studio.sidecars.restart",
        "--workspace",
        str(arguments.get("workspace_id") or "default"),
        "--operator",
        "--json",
    )
    completed = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("app sidecar restart capability failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("app sidecar restart returned invalid JSON") from error
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


def resolve_changeset(arguments: dict[str, Any], *, repo_root: Path) -> ChangeSet:
    """Resolve one explicit, isolated changeset and snapshot its current bytes."""
    explicit = arguments.get("changed_files")
    has_explicit = explicit is not None
    has_range = arguments.get("base_sha") is not None or arguments.get("head_sha") is not None
    if has_explicit == has_range:
        raise DevApplyError(
            "provide exactly one changeset: changed_files or base_sha with head_sha",
            report={},
        )
    if has_explicit:
        if not isinstance(explicit, list) or not explicit or not all(isinstance(item, str) for item in explicit):
            raise DevApplyError(
                "changed_files must be a non-empty array of repository-relative paths",
                report={},
            )
        changed = _validated_changed_files(explicit)
        base_sha = None
        head_sha = None
        source = "explicit_paths"
    else:
        if not isinstance(arguments.get("base_sha"), str) or not isinstance(arguments.get("head_sha"), str):
            raise DevApplyError("base_sha and head_sha must be provided together", report={})
        base_sha = _resolve_commit(repo_root, str(arguments["base_sha"]))
        head_sha = _resolve_commit(repo_root, str(arguments["head_sha"]))
        current_head = _resolve_commit(repo_root, "HEAD")
        if current_head != head_sha:
            raise DevApplyError("head_sha must resolve to the current checkout HEAD", report={})
        completed = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACDMRTUXB", base_sha, head_sha],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        changed = _validated_changed_files(completed.stdout.splitlines())
        if not changed:
            raise DevApplyError("the selected commit range contains no changed files", report={})
        _assert_paths_match_commit(repo_root, changed, head_sha=head_sha)
        source = "git_range"
    snapshot = _snapshot_paths(repo_root, changed)
    return ChangeSet(source, changed, base_sha, head_sha, snapshot)


def _validated_changed_files(paths: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw in paths:
        value = _normalize_path(raw)
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
            raise DevApplyError(f"unsafe changed path: {raw}", report={})
        normalized.add(candidate.as_posix())
    if not normalized:
        raise DevApplyError("changeset contains no changed files", report={})
    return tuple(sorted(normalized))


def _resolve_commit(repo_root: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise DevApplyError("base_sha/head_sha must resolve to Git commits", report={})
    return value


def _assert_paths_match_commit(repo_root: Path, paths: tuple[str, ...], *, head_sha: str) -> None:
    for relative in paths:
        completed = subprocess.run(
            ["git", "cat-file", "-e", f"{head_sha}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        path = repo_root / relative
        if completed.returncode != 0:
            if path.exists() or path.is_symlink():
                raise DevApplyError(f"changed path does not match head_sha: {relative}", report={})
            continue
        expected = subprocess.run(
            ["git", "show", f"{head_sha}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        ).stdout
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise DevApplyError(f"changed path does not match head_sha: {relative}", report={})


def _snapshot_paths(repo_root: Path, paths: tuple[str, ...]) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for relative in paths:
        path = repo_root / relative
        if path.is_symlink() or path.is_dir():
            raise DevApplyError(f"changed path must be a file or a deleted path: {relative}", report={})
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return snapshot


def _assert_changeset_unchanged(changeset: ChangeSet, *, repo_root: Path) -> None:
    observed = _snapshot_paths(repo_root, changeset.changed_files)
    if observed != changeset.path_sha256:
        raise DevApplyError("changeset bytes changed while dev apply was running", report={})


def _maverick_command(*tokens: str) -> list[str]:
    if str(os.environ.get("MAVERICK_ADMIN_USERNAME") or "").strip():
        return [sys.executable, "-m", "core.app_sdk.cli", *tokens]
    governed_cli = shutil.which("maverick")
    if governed_cli:
        return [governed_cli, *tokens]
    return [sys.executable, "-m", "core.app_sdk.cli", *tokens]


def _repo_root(arguments: dict[str, Any]) -> Path:
    value = arguments.get("repo_root")
    root = Path(str(value)).resolve() if value else Path(__file__).resolve().parents[3]
    if not (root / "AGENTS.md").is_file() or not (root / "apps/design-studio").is_dir():
        raise DevApplyError("repo_root is not the Maverick v3 repository", report={})
    return root


def _cache_root(arguments: dict[str, Any], repo_root: Path) -> Path:
    raw = arguments.get("cache_root") or os.environ.get("MAVERICK_OPENDESIGN_WEB_CACHE")
    return Path(str(raw)).resolve() if raw else repo_root / "tmp/opendesign-web-cache"


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


def _normalize_path(path: str) -> str:
    value = str(path).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value
