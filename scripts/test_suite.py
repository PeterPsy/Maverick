#!/usr/bin/env python3
"""Run Maverick tests by architectural layer, area, app, or changed paths."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]

LEVEL_CHOICES = ("fast", "unit", "contract", "app-backend", "integration", "e2e", "pre-merge", "full", "all")

AREA_DIRS = {
    "authorization": ["tests/integration/authorization"],
    "runtime": ["tests/unit/runtime", "tests/integration/runtime_api"],
    "providers": ["tests/unit/providers", "tests/e2e/provider_process"],
    "secrets": ["tests/unit/secret_store", "tests/integration/recovery"],
    "workspace": ["tests/unit/workspace", "tests/integration/workspace_api"],
    "cli-mcp": ["tests/integration/cli_mcp"],
    "app-hosting": ["tests/contracts/app_contract", "tests/integration/app_hosting"],
    "hosting": ["tests/contracts/app_contract", "tests/integration/app_hosting"],
    "app-sdk": ["tests/unit/app_sdk", "tests/integration/app_sdk"],
    "contracts": ["tests/contracts"],
    "install": ["tests/e2e/install"],
    "recovery": ["tests/unit/recovery", "tests/integration/recovery"],
    "observability": ["tests/unit/observability", "tests/integration/observability"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", choices=LEVEL_CHOICES, default="fast")
    parser.add_argument("--area", help="Root area name, 'apps', or an app id with apps/<app_id>/tests.")
    parser.add_argument("--app", help="Run tests for one app id from apps/<app_id>/tests.")
    parser.add_argument("--changed", action="store_true", help="Run the smallest suites implied by changed paths.")
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        help="Repository-relative path from an explicit immutable changeset; repeat for multiple paths.",
    )
    parser.add_argument("--jobs", default="auto", help="App test parallelism: 'auto' or a positive integer.")
    args = parser.parse_args()

    jobs = parse_jobs(args.jobs)

    if args.changed_path and not args.changed:
        parser.error("--changed-path requires --changed")
    if args.changed:
        explicit_paths = normalize_changed_paths(args.changed_path) if args.changed_path else None
        return run_changed(level=args.level, jobs=jobs, changed=explicit_paths)
    if args.app:
        return run_app(args.app, level=args.level)
    if args.area:
        return run_area(args.area, level=args.level, jobs=jobs)
    return run_level(args.level, jobs=jobs)


def parse_jobs(value: str) -> int:
    if value == "auto":
        return 0
    try:
        jobs = int(value)
    except ValueError:
        print("--jobs must be 'auto' or a positive integer.", file=sys.stderr)
        raise SystemExit(2)
    if jobs < 1:
        print("--jobs must be at least 1.", file=sys.stderr)
        raise SystemExit(2)
    return jobs


def run_level(level: str, *, jobs: int) -> int:
    if level in {"fast", "app-backend"}:
        return first_failure(
            [
                run_discover_dirs(["tests/unit", "tests/contracts"], level="fast"),
                run_app_test_dirs(app_test_dirs(), level="fast", jobs=jobs),
            ]
        )
    if level == "unit":
        return run_discover_dirs(["tests/unit"], level="unit")
    if level == "contract":
        return run_discover_dirs(["tests/contracts"], level="contract")
    if level == "integration":
        return first_failure(
            [
                run_discover_dirs(["tests/integration"], level="integration"),
                run_app_test_dirs(app_test_dirs(), level="integration", jobs=jobs),
            ]
        )
    if level == "e2e":
        return run_discover_dirs(["tests/e2e"], level="e2e")
    if level == "pre-merge":
        return first_failure(
            [
                run_level("fast", jobs=jobs),
                run_level("integration", jobs=jobs),
                run_command([sys.executable, "scripts/check_unused_imports.py"], level="fast"),
            ]
        )
    if level in {"full", "all"}:
        return first_failure(
            [
                run_level("pre-merge", jobs=jobs),
                run_app_full_only_tests(app_test_dirs(), jobs=jobs),
                run_level("e2e", jobs=jobs),
            ]
        )
    raise AssertionError(level)


def run_area(area: str, *, level: str, jobs: int) -> int:
    if area == "apps":
        return run_app_test_dirs(app_test_dirs(), level=level, jobs=jobs)
    app_directory = REPO_ROOT / "apps" / area / "tests"
    if app_directory.is_dir():
        return run_app(area, level=level)
    if area not in AREA_DIRS:
        print(f"Unknown test area `{area}`.", file=sys.stderr)
        return 2
    return run_discover_dirs(AREA_DIRS[area], level=level)


def run_app(app_id: str, *, level: str) -> int:
    app_directory = REPO_ROOT / "apps" / app_id / "tests"
    if not app_directory.is_dir():
        print(f"Unknown app test directory `apps/{app_id}/tests`.", file=sys.stderr)
        return 2
    return run_discover_dir(str(app_directory.relative_to(REPO_ROOT)), level=level)


def run_changed(*, level: str, jobs: int, changed: list[Path] | None = None) -> int:
    changed = changed_paths() if changed is None else changed
    if not changed:
        print("No changed paths detected; running fast suite.", flush=True)
        return run_level("fast", jobs=jobs)

    selected_app_dirs: set[str] = set()
    selected_dirs: set[str] = set()
    static_checks = False

    for path in changed:
        parts = path.parts
        if parts and parts[0] == "apps" and len(parts) >= 2:
            app_tests = REPO_ROOT / "apps" / parts[1] / "tests"
            if app_tests.is_dir():
                selected_app_dirs.add(str(app_tests.relative_to(REPO_ROOT)))
            else:
                selected_dirs.update(AREA_DIRS["app-hosting"])
            continue
        if parts and parts[0] == "core":
            selected_dirs.update(dirs_for_core_path(path))
            continue
        if parts and parts[0] == "tests":
            selected_dirs.update(dirs_for_test_path(path))
            continue
        if parts and parts[0] == "docs":
            selected_dirs.add("tests/contracts")
            continue
        if parts and parts[0] == "scripts":
            static_checks = True
            selected_dirs.add("tests/unit")

    print("Changed-path selection:", flush=True)
    for item in sorted(str(path) for path in changed):
        print(f"  {item}", flush=True)
    for directory in sorted(selected_dirs):
        print(f"  root tests: {directory}", flush=True)
    for directory in sorted(selected_app_dirs):
        print(f"  app tests: {directory}", flush=True)

    statuses: list[int] = []
    if selected_dirs:
        statuses.append(run_discover_dirs(sorted(selected_dirs), level=level))
    if selected_app_dirs:
        statuses.append(run_app_test_dirs(sorted(selected_app_dirs), level=level, jobs=jobs))
    if static_checks:
        statuses.append(run_command([sys.executable, "scripts/check_unused_imports.py"], level="fast"))
    if not statuses:
        statuses.append(run_level("fast", jobs=jobs))
    return first_failure(statuses)


def dirs_for_test_path(path: Path) -> set[str]:
    parts = path.parts
    if len(parts) >= 2 and parts[1] in {"unit", "contracts", "integration", "e2e"}:
        return {str(Path(*parts[:2]))}
    if len(parts) >= 3 and parts[1] == "support":
        return {"tests/unit", "tests/contracts", "tests/integration"}
    return {"tests/unit", "tests/contracts"}


def dirs_for_core_path(path: Path) -> set[str]:
    path_text = str(path)
    if path_text.startswith("core/runtime"):
        return {"tests/unit/runtime", "tests/integration/runtime_api"}
    if path_text.startswith("core/providers"):
        return {"tests/unit/providers", "tests/e2e/provider_process"}
    if path_text.startswith("core/secrets") or "secret" in path_text:
        return {"tests/unit/secret_store", "tests/integration/recovery"}
    if path_text.startswith("core/workspaces"):
        return {"tests/unit/workspace", "tests/integration/workspace_api"}
    if path_text.startswith("core/apps") or path_text.startswith("core/api/app"):
        return {"tests/contracts/app_contract", "tests/integration/app_hosting"}
    if path_text.startswith("core/cli") or path_text.startswith("core/mcp") or path_text.startswith("core/skills"):
        return {"tests/integration/cli_mcp"}
    if path_text.startswith("core/recovery"):
        return {"tests/unit/recovery", "tests/integration/recovery"}
    if path_text.startswith("core/observability"):
        return {"tests/unit/observability"}
    if path_text.startswith("core/api") or path_text.startswith("core/identity"):
        return {"tests/integration/authorization", "tests/integration/app_hosting"}
    return {"tests/unit", "tests/contracts"}


def run_discover_dirs(directories: list[str], *, level: str) -> int:
    statuses = []
    for directory in directories:
        if (REPO_ROOT / directory).is_dir():
            statuses.append(run_discover_dir(directory, level=level))
    return first_failure(statuses)


def run_app_test_dirs(directories: list[str], *, level: str, jobs: int) -> int:
    return run_app_test_dirs_with_env(directories, level=level, jobs=jobs, extra_env={})


def run_app_full_only_tests(directories: list[str], *, jobs: int) -> int:
    return run_app_test_dirs_with_env(directories, level="full", jobs=jobs, extra_env={"MAVERICK_TEST_FULL_ONLY": "1"})


def run_app_test_dirs_with_env(directories: list[str], *, level: str, jobs: int, extra_env: dict[str, str]) -> int:
    existing = [directory for directory in directories if (REPO_ROOT / directory).is_dir()]
    if not existing:
        return 0
    shards = app_test_shards(existing)
    max_workers = effective_app_workers(level=level, requested_jobs=jobs, shard_count=len(shards))
    if max_workers <= 1 or len(shards) <= 1:
        statuses = []
        for label, command, _weight in shards:
            statuses.append(run_command(command, level=level, extra_env=extra_env))
        return first_failure(statuses)
    print(f"Running {len(shards)} app test shards from {len(existing)} app directories with {max_workers} workers.", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                run_command_capture,
                command,
                level=level,
                extra_env=extra_env,
            ): label
            for label, command, _weight in shards
        }
        results: list[tuple[str, int, float, str]] = []
        for future in concurrent.futures.as_completed(futures):
            label = futures[future]
            returncode, elapsed, output = future.result()
            results.append((label, returncode, elapsed, output))
            print(f"$ {label}  # MAVERICK_TEST_LEVEL={level}", flush=True)
            if output:
                print(output, end="" if output.endswith("\n") else "\n", flush=True)
            print(f"completed in {elapsed:.2f}s with exit code {returncode}", flush=True)
    for label, returncode, _elapsed, _output in sorted(results):
        if returncode != 0:
            return returncode
    return 0


def effective_app_workers(*, level: str, requested_jobs: int, shard_count: int) -> int:
    if requested_jobs > 0:
        return min(requested_jobs, shard_count)
    cpu_count = os.cpu_count() or 1
    if level in {"integration", "full"}:
        return min(cpu_count, shard_count, 2)
    return min(cpu_count, shard_count, 4)


def app_test_shards(directories: list[str]) -> list[tuple[str, list[str], int]]:
    """Return app test commands without app-id special cases.

    Large app suites are split by test file so app-owned HTTP/bootstrap tests can
    run independently without forcing the entire app directory to be one serial
    bottleneck.
    """

    shards: list[tuple[str, list[str], int]] = []
    for directory in directories:
        test_files = sorted((REPO_ROOT / directory).glob("test_*.py"))
        if len(test_files) <= 1:
            weight = sum(path.stat().st_size for path in test_files) or 1
            command = [sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", "test_*.py"]
            shards.append((" ".join(command), command, weight))
            continue
        for path in test_files:
            pattern = path.name
            command = [sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", pattern]
            shards.append((" ".join(command), command, path.stat().st_size))
    return sorted(shards, key=lambda item: (-item[2], item[0]))


def app_test_dirs() -> list[str]:
    """Discover app-owned test directories without hardcoding app ids."""

    return [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "apps").glob("*/tests"))
        if path.is_dir()
    ]


def run_discover_dir(directory: str, *, level: str, extra_env: dict[str, str] | None = None) -> int:
    statuses = []
    for discovery_root in unittest_discovery_roots(directory):
        statuses.append(
            run_command(
                [sys.executable, "-m", "unittest", "discover", "-s", discovery_root, "-p", "test_*.py"],
                level=level,
                extra_env=extra_env or {},
            )
        )
    return first_failure(statuses)


def unittest_discovery_roots(directory: str) -> list[str]:
    """Partition tests so unittest also enters directories without ``__init__.py``."""
    base = REPO_ROOT / directory
    roots: set[Path] = set()
    for test_file in base.rglob("test_*.py"):
        discovery_root = base
        current = base
        for part in test_file.parent.relative_to(base).parts:
            current /= part
            if not (current / "__init__.py").is_file():
                discovery_root = current
        roots.add(discovery_root)
    return [str(path.relative_to(REPO_ROOT)) for path in sorted(roots)]


def changed_paths() -> list[Path]:
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    paths: set[Path] = set()
    for command in commands:
        completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        for line in completed.stdout.splitlines():
            if line.strip():
                paths.add(Path(line.strip()))
    return sorted(paths)


def normalize_changed_paths(values: list[str]) -> list[Path]:
    """Validate caller-owned changed paths without consulting the shared working tree."""
    paths: set[Path] = set()
    for raw in values:
        value = str(raw).strip().replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
            raise SystemExit(f"Invalid --changed-path value: {raw}")
        paths.add(Path(*candidate.parts))
    if not paths:
        raise SystemExit("At least one --changed-path is required when explicit paths are selected.")
    return sorted(paths)


def run_command(command: list[str], *, level: str, extra_env: dict[str, str] | None = None) -> int:
    completed, elapsed = _run_subprocess(command, level=level, capture_output=False, extra_env=extra_env or {})
    print(f"completed in {elapsed:.2f}s with exit code {completed.returncode}", flush=True)
    return completed.returncode


def run_command_capture(command: list[str], *, level: str, extra_env: dict[str, str] | None = None) -> tuple[int, float, str]:
    completed, elapsed = _run_subprocess(command, level=level, capture_output=True, extra_env=extra_env or {})
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, elapsed, output


def _run_subprocess(
    command: list[str],
    *,
    level: str,
    capture_output: bool,
    extra_env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], float]:
    env = os.environ.copy()
    env.setdefault("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS", "1")
    env.setdefault("MAVERICK_ADMIN_USERNAME", "admin")
    env.setdefault("MAVERICK_ADMIN_PASSWORD", "maverick")
    env.setdefault("MAVERICK_RUNTIME_API_SECRET", "maverick-test-runtime-api-secret")
    env.setdefault("MAVERICK_SECRET_STORE_KEY", "maverick-test-secret-store-key")
    env["MAVERICK_TEST_LEVEL"] = level
    env.update(extra_env)

    started = time.monotonic()
    if not capture_output:
        print(f"$ {' '.join(command)}  # MAVERICK_TEST_LEVEL={level}", flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, text=True, capture_output=capture_output)
    elapsed = time.monotonic() - started
    return completed, elapsed


def first_failure(statuses: list[int]) -> int:
    for status in statuses:
        if status != 0:
            return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
