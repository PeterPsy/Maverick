#!/usr/bin/env python3
"""Report local generated/runtime artifact noise without mutating the checkout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


GENERATED_DIST_FRAGMENT = "/frontend/dist/"
CACHE_NAMES = {"__pycache__", "node_modules", ".pytest_cache", ".mypy_cache"}
LOCAL_WORKSPACE_FRAGMENTS = ("/runtime/", "/logs/", "/tmp/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when hygiene findings are present.")
    args = parser.parse_args(argv)

    root = args.repository_root.resolve()
    report = build_report(root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 1 if args.strict and report["summary"]["finding_count"] else 0


def build_report(root: Path) -> dict[str, object]:
    status_entries = _git_status(root)
    tracked_dist_changes = [
        entry for entry in status_entries if GENERATED_DIST_FRAGMENT in f"/{entry['path']}"
    ]
    workspace_local_changes = [
        entry
        for entry in status_entries
        if entry["path"].startswith("workspaces/") and any(fragment in f"/{entry['path']}/" for fragment in LOCAL_WORKSPACE_FRAGMENTS)
    ]
    cache_directories = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir() and path.name in CACHE_NAMES and ".git" not in path.parts
    ]
    findings = {
        "tracked_frontend_dist_changes": tracked_dist_changes,
        "workspace_runtime_log_tmp_changes": workspace_local_changes,
        "cache_directories": sorted(cache_directories),
    }
    finding_count = sum(len(value) for value in findings.values())
    return {
        "repository_root": str(root),
        "summary": {
            "finding_count": finding_count,
            "tracked_frontend_dist_change_count": len(tracked_dist_changes),
            "workspace_runtime_log_tmp_change_count": len(workspace_local_changes),
            "cache_directory_count": len(cache_directories),
        },
        "findings": findings,
        "guidance": [
            "Keep intentional frontend/dist changes paired with source changes and official frontend rebuild output.",
            "Remove cache directories and local runtime/log/tmp artifacts before review when they are not part of the task.",
            "Do not delete unrelated dirty work; separate it before cleanup.",
        ],
    }


def print_human(report: dict[str, object]) -> None:
    summary = report["summary"]
    print(f"Repository: {report['repository_root']}")
    print(f"Findings: {summary['finding_count']}")
    for key, values in report["findings"].items():
        print(f"\n{key}: {len(values)}")
        for value in values[:50]:
            if isinstance(value, dict):
                print(f"  {value['status']} {value['path']}")
            else:
                print(f"  {value}")
        if len(values) > 50:
            print(f"  ... {len(values) - 50} more")


def _git_status(root: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    entries = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status = line[:2]
        path = line[3:] if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append({"status": status, "path": path})
    return entries


if __name__ == "__main__":
    sys.exit(main())
