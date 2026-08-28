#!/usr/bin/env python3
"""Operate the one-time, same-version native OpenDesign data cutover."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from native_cutover_files import NativeCutoverFileError
from native_cutover_state import (
    MARKER_FILE,
    NativeDataCutoverError,
    begin_native_writer_activation,
    finish_native_writer_activation,
    new_cutover_id,
    read_marker,
)
from native_cutover_quiescence import quiesce_native_host, release_native_host
from native_data_cutover import perform_native_data_cutover
from official_opendesign_release import OfficialReleaseError, verify_official_installation


CORE_SERVICE = "maverick-core.service"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    args = _parser().parse_args()
    if args.action == "status":
        marker = read_marker(args.data_root / MARKER_FILE)
        _emit(marker)
        return
    if args.action == "prepare":
        identifier = args.cutover_id or new_cutover_id()
        _stop_managed_writer(
            args.data_root,
            cutover_id=identifier,
            confirmed=args.confirm_writers_stopped,
            workspace_id=args.workspace_id,
        )
        installation = verify_official_installation(args.installation)
        marker = perform_native_data_cutover(
            args.data_root,
            installation,
            cutover_id=identifier,
        )
        _emit(marker)
        return
    if args.action == "activate":
        if not args.confirm_writers_stopped:
            raise NativeDataCutoverError("explicit writer-stop confirmation is required")
        begin_native_writer_activation(args.data_root, cutover_id=args.cutover_id)
        release_native_host(args.data_root, cutover_id=args.cutover_id)
        try:
            readiness = _request_sidecar_control("prewarm", workspace_id=args.workspace_id)
            if readiness.get("ready") is not True:
                raise NativeDataCutoverError("Core did not confirm native OpenDesign readiness")
        except Exception:
            finish_native_writer_activation(
                args.data_root,
                cutover_id=args.cutover_id,
                ready=False,
            )
            raise
        _emit(
            finish_native_writer_activation(
                args.data_root,
                cutover_id=args.cutover_id,
                ready=True,
            )
        )
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
    prepare.add_argument("--workspace-id", default="default")
    prepare.add_argument("--confirm-writers-stopped", action="store_true")
    activate = subparsers.add_parser(
        "activate", help="close legacy rollback immediately before starting Core"
    )
    activate.add_argument("--data-root", required=True, type=Path)
    activate.add_argument("--cutover-id", required=True)
    activate.add_argument("--workspace-id", default="default")
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


def _stop_managed_writer(
    app_data_root: Path,
    *,
    cutover_id: str,
    confirmed: bool,
    workspace_id: str = "default",
) -> None:
    if not confirmed:
        raise NativeDataCutoverError("explicit writer-stop confirmation is required")
    quiesce_native_host(app_data_root, cutover_id=cutover_id)
    try:
        stopped = _request_sidecar_control("stop", workspace_id=workspace_id)
    except Exception:
        _require_core_inactive()
        return
    if stopped.get("ready") is not False:
        raise NativeDataCutoverError("Core did not confirm the OpenDesign writer stop")


def _require_core_inactive() -> None:
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


def _request_sidecar_control(operation: str, *, workspace_id: str) -> dict[str, Any]:
    repository = str(REPOSITORY_ROOT)
    if repository not in sys.path:
        sys.path.insert(0, repository)
    from core.api.sidecar_control import request_sidecar_control

    try:
        return request_sidecar_control(
            REPOSITORY_ROOT,
            operation=operation,
            workspace_id=workspace_id,
            app_id="design-studio",
            timeout_seconds=45.0,
        )
    except Exception as error:
        raise NativeDataCutoverError("live Core sidecar control failed") from error


def _emit(marker: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "cutover": marker}, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (NativeCutoverFileError, NativeDataCutoverError, OfficialReleaseError) as error:
        raise SystemExit(str(error)) from error
