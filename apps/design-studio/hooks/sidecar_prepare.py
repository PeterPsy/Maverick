"""Recover host-only update state and project the selected release to the sidecar."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from native_cutover_files import atomic_write_json, real_directory  # noqa: E402
from native_cutover_quiescence import reject_if_native_host_quiesced  # noqa: E402
from native_official_update_recovery import (  # noqa: E402
    recover_official_update_locked,
)
from official_bridge_contracts import (  # noqa: E402
    bundled_delegation_contract,
    read_delegation_contract,
    write_bridge_contracts,
)
from official_opendesign_release import load_official_release  # noqa: E402
from official_release_selection import ensure_release_selection  # noqa: E402
from official_update_lock import official_update_lock  # noqa: E402


LAUNCH_CONFIGURATION_ENV = "MAVERICK_APP_OPENDESIGN_LAUNCH_CONFIGURATION"


def main() -> None:
    payload = read_entrypoint_payload()
    if (
        payload.app_id != "design-studio"
        or payload.raw.get("sidecar_id") != "opendesign"
        or payload.raw.get("managed_writer_stopped") is not True
        or not payload.workspace_id
    ):
        raise SystemExit("Design Studio sidecar preparation identity is invalid.")
    root = real_directory(Path(payload.data_root), label="Design Studio data root")

    # A live updater owns the lock through its prewarm. It has already released
    # quiescence before that launch; otherwise the check below stays fail-closed.
    with official_update_lock(root) as acquired:
        if acquired:
            recover_official_update_locked(
                root,
                workspace_id=payload.workspace_id,
                sidecar_control=None,
                managed_writer_stopped=True,
                resume_writer=False,
            )
    reject_if_native_host_quiesced(root)

    bundled = load_official_release()
    selection = ensure_release_selection(root, bundled)
    delegation = read_delegation_contract(root, selection.release)
    if (
        delegation.get("state") == "degraded"
        and selection.release.manifest_digest == bundled.manifest_digest
    ):
        write_bridge_contracts(
            root,
            selection.release,
            delegation=bundled_delegation_contract(),
        )
        delegation = read_delegation_contract(root, selection.release)
    atomic_write_json(
        root / "bridge-capabilities.json",
        {
            "schema_version": "1",
            "manifest_digest": selection.release.manifest_digest,
            "delegation": delegation,
        },
    )
    launch_configuration = json.dumps(
        {
            "schema_version": "1",
            "release": selection.release.descriptor(),
            "delegation": delegation,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    emit_json(
        {
            "ok": True,
            "environment": {LAUNCH_CONFIGURATION_ENV: launch_configuration},
        }
    )


if __name__ == "__main__":
    main()
