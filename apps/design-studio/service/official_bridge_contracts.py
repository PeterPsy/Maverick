"""Release-bound capability evidence for optional external OpenDesign bridges."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import stat
from typing import Any
from uuid import uuid4

from native_cutover_files import atomic_write_json, real_directory
from official_inventory_process import running_official_api
from official_opendesign_release import OfficialInstallation, OfficialRelease


BRIDGE_CONTRACTS_FILE = "official-bridge-contracts.json"


def probe_delegation_contract(
    installation: OfficialInstallation,
    *,
    data_dir: Path,
    log_path: Path,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Exercise the public delegation API only on a disposable data copy."""
    identity = f"maverick-update-{uuid4().hex[:16]}"
    with running_official_api(
        installation,
        data_dir=data_dir,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
    ) as client:
        created = client.send_json(
            "POST",
            "/api/projects",
            {
                "id": identity,
                "name": "Maverick update compatibility probe",
                "metadata": {"kind": "prototype", "compatibilityProbe": True},
                "skipDiscoveryBrief": True,
                "conversationMode": "design",
            },
        )
        project = created.get("project")
        if not isinstance(project, dict) or project.get("id") != identity:
            raise RuntimeError("official OpenDesign project creation contract changed")
        conversation_id = created.get("conversationId")
        if not isinstance(conversation_id, str) or not conversation_id:
            conversation = client.send_json(
                "POST",
                f"/api/projects/{identity}/conversations",
                {"title": "Compatibility probe", "sessionMode": "design"},
            ).get("conversation")
            conversation_id = conversation.get("id") if isinstance(conversation, dict) else None
        if not isinstance(conversation_id, str) or not conversation_id:
            raise RuntimeError("official OpenDesign conversation creation contract changed")
        message_id = f"message-{uuid4().hex[:16]}"
        message = client.send_json(
            "PUT",
            f"/api/projects/{identity}/conversations/{conversation_id}/messages/{message_id}",
            {
                "role": "user",
                "content": "Visible compatibility probe.",
                "attachments": [],
                "startedAt": 1,
                "endedAt": 1,
            },
        ).get("message")
        if not isinstance(message, dict) or message.get("id") != message_id:
            raise RuntimeError("official OpenDesign message contract changed")
        uploaded = client.send_json(
            "POST",
            f"/api/projects/{identity}/files",
            {
                "name": ".maverick/compatibility-probe.txt",
                "content": "cHJvYmU=",
                "encoding": "base64",
                "overwrite": True,
            },
        ).get("file")
        if not isinstance(uploaded, dict):
            raise RuntimeError("official OpenDesign file upload contract changed")
        client.get_json(f"/api/projects/{identity}")
        client.get_json(f"/api/projects/{identity}/conversations")
        client.get_json(f"/api/projects/{identity}/conversations/{conversation_id}/messages")
        client.get_json("/api/runs")
        assistant_id = f"assistant-{uuid4().hex[:16]}"
        started = client.send_json(
            "POST",
            "/api/runs",
            {
                "message": "Visible compatibility probe.",
                "currentPrompt": "Visible compatibility probe.",
                "projectId": identity,
                "conversationId": conversation_id,
                "sessionMode": "design",
                "assistantMessageId": assistant_id,
                "clientRequestId": f"maverick-update:{uuid4().hex}",
                "attachments": [],
            },
        )
        run_id = started.get("runId")
        if (
            not isinstance(run_id, str)
            or not run_id
            or started.get("conversationId") != conversation_id
            or started.get("assistantMessageId") != assistant_id
        ):
            raise RuntimeError("official OpenDesign run creation contract changed")
        run = client.get_json(f"/api/runs/{run_id}")
        if run.get("id") != run_id:
            raise RuntimeError("official OpenDesign run status contract changed")
        canceled = client.send_json("POST", f"/api/runs/{run_id}/cancel", {})
        if not isinstance(canceled.get("run"), dict):
            raise RuntimeError("official OpenDesign run cancellation contract changed")
        result = client.get_json(f"/api/runs/{run_id}/result-package")
        if not isinstance(result.get("run"), dict):
            raise RuntimeError("official OpenDesign result reference contract changed")
    return {
        "state": "ready",
        "contract": "public-opendesign-delegation-v1",
        "evidence": "disposable-public-api-probe",
    }


def write_bridge_contracts(
    app_data_root: Path,
    release: OfficialRelease,
    *,
    delegation: dict[str, Any],
) -> dict[str, Any]:
    root = real_directory(app_data_root, label="Design Studio data root", create=True)
    normalized = _delegation_status(delegation)
    payload = {
        "schema_version": "1",
        "kind": "design-studio-official-bridge-contracts",
        "checked_at": _utc_now(),
        "manifest_digest": release.manifest_digest,
        "delegation": normalized,
    }
    atomic_write_json(root / BRIDGE_CONTRACTS_FILE, payload)
    return payload


def read_delegation_contract(app_data_root: Path, release: OfficialRelease) -> dict[str, Any]:
    """Return degraded evidence on any mismatch; native startup must continue."""
    path = app_data_root / BRIDGE_CONTRACTS_FILE
    try:
        metadata = path.lstat()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("unsafe bridge contract file")
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "kind", "checked_at", "manifest_digest", "delegation"}
            or payload.get("schema_version") != "1"
            or payload.get("kind") != "design-studio-official-bridge-contracts"
            or payload.get("manifest_digest") != release.manifest_digest
            or not isinstance(payload.get("checked_at"), str)
        ):
            raise ValueError("bridge contract mismatch")
        return _delegation_status(payload.get("delegation"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {"state": "degraded", "reason": "not_checked_for_selected_release"}


def bundled_delegation_contract() -> dict[str, Any]:
    """The pinned release contract was certified by the native delegation tests."""
    return {
        "state": "ready",
        "contract": "public-opendesign-delegation-v1",
        "evidence": "bundled-release-acceptance",
    }


def _delegation_status(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("state") not in {"ready", "degraded", "disabled"}:
        raise ValueError("delegation bridge contract status is invalid")
    allowed = {"state", "contract", "evidence", "reason"}
    if set(value) - allowed or any(not isinstance(item, str) or not item for item in value.values()):
        raise ValueError("delegation bridge contract status is invalid")
    return dict(value)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "BRIDGE_CONTRACTS_FILE",
    "bundled_delegation_contract",
    "probe_delegation_contract",
    "read_delegation_contract",
    "write_bridge_contracts",
]
