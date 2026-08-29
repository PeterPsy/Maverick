#!/usr/bin/env python3
"""Run maintained end-to-end gates for the official native OpenDesign host."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(SERVICE_ROOT))

from core.apps.artifact_mounts import platform_artifact_store_root  # noqa: E402
from official_opendesign_release import load_official_release  # noqa: E402
from opencode_runtime import RUNTIME_RELATIVE_PATH  # noqa: E402


PROFILES = {"quick", "affected", "release", "migration", "hosted"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="release")
    parser.add_argument("--installation", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--changed-file", action="append", default=[])
    args = parser.parse_args()

    started = time.monotonic()
    commands = _commands(args.profile, args.installation)
    completed: list[dict[str, object]] = []
    for command, cwd in commands:
        command_started = time.monotonic()
        subprocess.run(command, cwd=cwd, check=True)
        completed.append(
            {
                "command": command,
                "duration_ms": round((time.monotonic() - command_started) * 1000, 3),
            }
        )
    evidence = {
        "schema_version": "1",
        "kind": "design-studio-official-native-e2e",
        "profile": args.profile,
        "status": "passed",
        "completed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "changed_file_count": len(args.changed_file),
        "commands": completed,
    }
    if args.evidence_output:
        output = args.evidence_output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


def _commands(profile: str, requested_installation: Path | None) -> list[tuple[list[str], Path]]:
    quick_tests = [
        "apps.design-studio.tests.test_native_thin_host",
        "apps.design-studio.tests.test_model_access_bridge",
        "apps.design-studio.tests.test_native_delegation",
    ]
    migration_tests = [
        "apps.design-studio.tests.test_native_data_cutover",
        "apps.design-studio.tests.test_official_public_inventory",
        "apps.design-studio.tests.test_official_updates",
    ]
    commands: list[tuple[list[str], Path]] = []
    if profile == "quick":
        commands.append(([sys.executable, "-m", "unittest", *quick_tests], REPOSITORY_ROOT))
        commands.append((["npm", "test"], APP_ROOT))
        return commands
    if profile == "migration":
        commands.append(([sys.executable, "-m", "unittest", *migration_tests], REPOSITORY_ROOT))
        return commands
    if profile == "hosted":
        commands.append(([
            sys.executable,
            "-m",
            "unittest",
            "apps.design-studio.tests.test_native_thin_host",
        ], REPOSITORY_ROOT))
    else:
        commands.append(([
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "apps/design-studio/tests",
            "-p",
            "test_*.py",
        ], REPOSITORY_ROOT))
    commands.extend(
        [
            (["npm", "test"], APP_ROOT),
            (["npm", "run", "build"], APP_ROOT),
        ]
    )
    if profile in {"release", "hosted"}:
        installation = _installation(requested_installation)
        opencode = _opencode_runtime()
        commands.extend(
            [
                ([
                    sys.executable,
                    str(SERVICE_ROOT / "smoke_official_opendesign.py"),
                    "--installation",
                    str(installation),
                ], REPOSITORY_ROOT),
                ([
                    sys.executable,
                    str(SERVICE_ROOT / "smoke_native_product.py"),
                    "--installation",
                    str(installation),
                    "--opencode-runtime",
                    str(opencode),
                ], REPOSITORY_ROOT),
                (["node", "tests/native_deep_link.e2e.mjs"], APP_ROOT),
            ]
        )
    return commands


def _installation(requested: Path | None) -> Path:
    if requested is not None:
        return requested.resolve()
    configured = os.environ.get("MAVERICK_OPENDESIGN_INSTALLATION", "").strip()
    if configured:
        return Path(configured).resolve()
    release = load_official_release()
    store = platform_artifact_store_root(REPOSITORY_ROOT)
    installation = store / "design-studio/opendesign/official" / release.digest_key
    if not installation.is_dir():
        raise SystemExit(
            "The verified official OpenDesign installation is missing; run the Design Studio "
            "install hook or pass --installation."
        )
    return installation


def _opencode_runtime() -> Path:
    configured = os.environ.get("MAVERICK_OPENCODE_RUNTIME", "").strip()
    if configured:
        return Path(configured).resolve()
    store = platform_artifact_store_root(REPOSITORY_ROOT)
    runtime = store / "design-studio/opendesign" / RUNTIME_RELATIVE_PATH
    if not runtime.is_dir():
        raise SystemExit(
            "The verified OpenCode adapter runtime is missing; upgrade/reinstall Design Studio "
            "or set MAVERICK_OPENCODE_RUNTIME."
        )
    return runtime


if __name__ == "__main__":
    main()
