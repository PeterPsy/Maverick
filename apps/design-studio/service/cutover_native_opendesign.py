#!/usr/bin/env python3
"""Operate the one-time, same-version native OpenDesign data cutover."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from native_cutover_files import NativeCutoverFileError
from native_cutover_state import (
    MARKER_FILE,
    NativeDataCutoverError,
    begin_native_writer_activation,
    finish_native_writer_activation,
    read_marker,
)
from native_data_cutover import perform_native_data_cutover
from official_opendesign_release import OfficialReleaseError, verify_official_installation


CORE_SERVICE = "maverick-core.service"
WRITER_PROCESS_MARKERS = (
    "opendesign_launcher.py",
    "opendesign_process.py",
)


def main() -> None:
    args = _parser().parse_args()
    if args.action == "status":
        marker = read_marker(args.data_root / MARKER_FILE)
        _emit(marker)
        return
    if args.action == "prepare":
        _require_writers_stopped(args.confirm_writers_stopped)
        installation = verify_official_installation(args.installation)
        marker = perform_native_data_cutover(
            args.data_root,
            installation,
            cutover_id=args.cutover_id,
        )
        _emit(marker)
        return
    if args.action == "activate":
        _require_writers_stopped(args.confirm_writers_stopped)
        _emit(begin_native_writer_activation(args.data_root, cutover_id=args.cutover_id))
        return
    if args.action == "finalize":
        _emit(
            finish_native_writer_activation(
                args.data_root,
                cutover_id=args.cutover_id,
                ready=args.ready,
            )
        )
        return
    raise NativeDataCutoverError("unsupported native cutover action")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare", help="back up, certify, and select native data")
    prepare.add_argument("--data-root", required=True, type=Path)
    prepare.add_argument("--installation", required=True, type=Path)
    prepare.add_argument("--cutover-id")
    prepare.add_argument("--confirm-writers-stopped", action="store_true")
    activate = subparsers.add_parser(
        "activate", help="close legacy rollback immediately before starting Core"
    )
    activate.add_argument("--data-root", required=True, type=Path)
    activate.add_argument("--cutover-id", required=True)
    activate.add_argument("--confirm-writers-stopped", action="store_true")
    finalize = subparsers.add_parser("finalize", help="record native readiness after startup")
    finalize.add_argument("--data-root", required=True, type=Path)
    finalize.add_argument("--cutover-id", required=True)
    readiness = finalize.add_mutually_exclusive_group(required=True)
    readiness.add_argument("--ready", action="store_true")
    readiness.add_argument("--failed", action="store_false", dest="ready")
    status = subparsers.add_parser("status", help="read the redaction-safe cutover marker")
    status.add_argument("--data-root", required=True, type=Path)
    return parser


def _require_writers_stopped(confirmed: bool) -> None:
    if not confirmed:
        raise NativeDataCutoverError("explicit writer-stop confirmation is required")
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", CORE_SERVICE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as error:
        raise NativeDataCutoverError("Core writer state could not be verified") from error
    if result.returncode == 0:
        raise NativeDataCutoverError("Maverick Core must be stopped before native cutover")
    if result.returncode not in {3, 4}:
        raise NativeDataCutoverError("Maverick Core writer state is indeterminate")
    active = _active_writer_processes()
    if active:
        raise NativeDataCutoverError(
            "OpenDesign writer processes remain active: " + ",".join(str(pid) for pid in active)
        )


def _active_writer_processes(proc_root: Path = Path("/proc")) -> list[int]:
    active: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except OSError:
            continue
        if any(marker in command for marker in WRITER_PROCESS_MARKERS):
            active.append(int(entry.name))
    return sorted(active)


def _emit(marker: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "cutover": marker}, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (NativeCutoverFileError, NativeDataCutoverError, OfficialReleaseError) as error:
        raise SystemExit(str(error)) from error
