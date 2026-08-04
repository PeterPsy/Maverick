#!/usr/bin/env python3
"""Run the full upstream acceptance once, separately from artifact packaging."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from opendesign_supply_chain import (
    SupplyChainError,
    read_json,
    sha256_file,
    validate_certification_record,
    validate_manifest,
    validate_source_identity,
)


START_AVAILABLE_BYTES = 4 * 1024**3
STOP_AVAILABLE_BYTES = int(2.5 * 1024**3)
POLL_SECONDS = 5


def mem_available_bytes(meminfo: Path = Path("/proc/meminfo")) -> int:
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                return int(fields[1]) * 1024
    raise SupplyChainError("MemAvailable is unavailable")


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


def run_bounded(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path) -> int:
    available = mem_available_bytes()
    if available < START_AVAILABLE_BYTES:
        raise SupplyChainError(
            f"refusing heavy acceptance command with MemAvailable={available}; need {START_AVAILABLE_BYTES}"
        )
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while True:
                try:
                    return process.wait(timeout=POLL_SECONDS)
                except subprocess.TimeoutExpired:
                    if mem_available_bytes() < STOP_AVAILABLE_BYTES:
                        _stop_process_group(process)
                        return 125
        except BaseException:
            _stop_process_group(process)
            raise


def run_acceptance(source: Path, manifest_path: Path, output_dir: Path) -> dict[str, object]:
    manifest = read_json(manifest_path)
    validate_manifest(manifest)
    service_root = manifest_path.parent
    record = validate_certification_record(service_root, manifest)
    validate_source_identity(source, manifest)
    output_dir.mkdir(parents=True, exist_ok=False)
    environment = certification_environment(output_dir)
    commands = record["commands"]
    assert isinstance(commands, dict)
    results: dict[str, int | None] = {"install": None, "web": None, "daemon": None}
    logs: dict[str, dict[str, object]] = {}
    for name in ("install", "web", "daemon"):
        command = commands[name]
        assert isinstance(command, list) and all(isinstance(item, str) for item in command)
        log_path = output_dir / f"{name}.log"
        results[name] = run_bounded(command, cwd=source, env=environment, log_path=log_path)
        logs[name] = {
            "file": log_path.name,
            "sha256": sha256_file(log_path),
            "size_bytes": log_path.stat().st_size,
        }
        if name == "install" and results[name] != 0:
            break
    completed_suites = results["web"] is not None and results["daemon"] is not None
    if any(code == 125 for code in results.values()):
        status = "protective_stop"
    elif completed_suites and results["web"] == results["daemon"] == 0:
        status = "passed"
    elif completed_suites:
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
    result_path = output_dir / "acceptance-result.json"
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def certification_plan(manifest_path: Path) -> dict[str, object]:
    manifest = read_json(manifest_path)
    validate_manifest(manifest)
    record = validate_certification_record(manifest_path.parent, manifest)
    return {"upstream": record["upstream"], "policy": record["policy"], "commands": record["commands"]}


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    service_root = Path(__file__).resolve().parent
    parser.add_argument("--manifest", type=Path, default=service_root / "opendesign_bundle.json")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    try:
        if args.plan:
            print(json.dumps(certification_plan(args.manifest), indent=2, sort_keys=True))
            return 0
        if args.source is None or args.output_dir is None:
            parser.error("--source and --output-dir are required unless --plan is used")
        result = run_acceptance(args.source, args.manifest, args.output_dir)
    except (OSError, SupplyChainError, ValueError) as exc:
        print(f"OpenDesign upstream certification failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
