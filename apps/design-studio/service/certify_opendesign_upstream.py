#!/usr/bin/env python3
"""Run the full upstream acceptance once, separately from artifact packaging."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from opendesign_artifact import sha256_file
from opendesign_process import (
    BuildProcessError,
    activate_runtime_attachment,
    run_command,
    signal_guard,
)
from opendesign_supply_chain import (
    SupplyChainError,
    read_json,
    validate_certification_record,
    validate_manifest,
    validate_source_identity,
)


def certification_environment(output_dir: Path) -> dict[str, str]:
    cert_home = output_dir / "home"
    cert_tmp = output_dir / "tmp"
    cert_home.mkdir(mode=0o700)
    cert_tmp.mkdir(mode=0o700)
    return {
        "CI": "true",
        "HOME": str(cert_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MALLOC_ARENA_MAX": "1",
        "NODE_OPTIONS": "--max-old-space-size=1536",
        "NO_COLOR": "1",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TMPDIR": str(cert_tmp),
        "TZ": "UTC",
    }


def run_acceptance(
    source: Path,
    manifest_path: Path,
    output_dir: Path,
    *,
    runtime_session_id: str | None,
) -> dict[str, object]:
    manifest = read_json(manifest_path)
    validate_manifest(manifest)
    record = validate_certification_record(manifest_path.parent, manifest)
    validate_source_identity(source, manifest)
    output_dir.mkdir(parents=True, exist_ok=False)
    environment = certification_environment(output_dir)
    commands = record["commands"]
    if not isinstance(commands, dict):
        raise SupplyChainError("certification commands are invalid")
    results: dict[str, int | None] = {"install": None, "web": None, "daemon": None}
    logs: dict[str, dict[str, object]] = {}
    for name in ("install", "web", "daemon"):
        command = commands[name]
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise SupplyChainError(f"certification command is invalid: {name}")
        log_path = output_dir / f"{name}.log"
        result = run_command(
            command,
            cwd=source,
            env=environment,
            log_path=log_path,
            heavy=True,
            check=False,
            runtime_session_id=runtime_session_id,
        )
        results[name] = result.returncode
        logs[name] = {
            "file": log_path.name,
            "sha256": sha256_file(log_path),
            "size_bytes": log_path.stat().st_size,
        }
        if name == "install" and result.returncode != 0:
            break
    completed = results["web"] is not None and results["daemon"] is not None
    if completed and results["web"] == results["daemon"] == 0:
        status = "passed"
    elif completed:
        status = "completed_with_failures"
    else:
        status = "incomplete"
    payload: dict[str, object] = {
        "schema_version": "1",
        "kind": "opendesign_upstream_acceptance_result",
        "upstream": record["upstream"],
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "exit_codes": results,
        "logs": logs,
        "policy": record["policy"],
    }
    (output_dir / "acceptance-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def certification_plan(manifest_path: Path) -> dict[str, object]:
    manifest = read_json(manifest_path)
    validate_manifest(manifest)
    record = validate_certification_record(manifest_path.parent, manifest)
    return {"upstream": record["upstream"], "policy": record["policy"], "commands": record["commands"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    service_root = Path(__file__).resolve().parent
    parser.add_argument("--manifest", type=Path, default=service_root / "opendesign_bundle.json")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--allow-operator-detached", action="store_true")
    args = parser.parse_args()
    try:
        if args.plan:
            print(json.dumps(certification_plan(args.manifest), indent=2, sort_keys=True))
            return 0
        if args.source is None or args.output_dir is None:
            parser.error("--source and --output-dir are required unless --plan is used")
        with signal_guard():
            runtime_session_id = activate_runtime_attachment(
                allow_operator_detached=args.allow_operator_detached
            )
            result = run_acceptance(
                args.source,
                args.manifest,
                args.output_dir,
                runtime_session_id=runtime_session_id,
            )
    except (BuildProcessError, OSError, SupplyChainError, ValueError) as exc:
        print(f"OpenDesign upstream certification failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
