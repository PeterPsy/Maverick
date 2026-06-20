"""Phase 1 service layer for Senses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import secrets
import sqlite3
import string
from typing import Any
import uuid

from database import (
    SCHEMA_VERSION,
    connect,
    decode_json_object,
    encode_json_object,
    ensure_schema,
    health_payload,
    now_timestamp,
    require_workspace_id,
    settings_payload,
)


APP_ID = "senses"
APP_NAME = "Senses"
APP_VERSION = "0.2.0"
PHASE = "phase-1"
PAIRING_CODE_ALPHABET = "".join(char for char in string.ascii_uppercase + string.digits if char not in {"0", "O", "I", "1"})
PAIRING_CODE_LENGTH = 8
PAIRING_TTL_MIN_SECONDS = 60
PAIRING_TTL_MAX_SECONDS = 3600
ADMIN_WORKSPACE_ROLES = {"admin"}
ADMIN_PLATFORM_ROLES = {"admin"}
REQUIRED_DEPENDENCIES = (
    {
        "alias": "storage-file-content-write",
        "interface": "file.content.write",
        "version": "^1",
        "required": True,
    },
    {
        "alias": "storage-file-catalog",
        "interface": "file.catalog",
        "version": "^1",
        "required": True,
    },
)
DECLARED_BACKEND_ACTIONS = (
    "manifest",
    "health",
    "overview",
    "pairing.start",
    "pairing.complete",
    "pairing.status",
    "devices.list",
    "devices.revoke",
    "settings.get",
    "settings.update",
)
DEFERRED_ACTIONS = (
    "ingest.frame",
    "routing.dispatch_capture",
    "device-token ingress",
)


def handle_action(data_root: Path, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    action = normalize_action(payload.get("action"))
    workspace_id = workspace_id_from_payload(payload)
    if workspace_id is None:
        return error_payload(
            400,
            "missing_workspace_id",
            "Senses requires a workspace_id from the Maverick host payload.",
        )

    dependencies = dependency_resolution_payload(payload.get("_app_dependencies") or payload.get("app_dependencies"))
    actor = actor_from_payload(payload)
    if action in {"manifest", "operations.manifest"}:
        return 200, manifest_payload(workspace_id=workspace_id, dependencies=dependencies, actor=actor)
    if action in {"health", "health.check", "status"}:
        return 200, health_action_payload(data_root, workspace_id, dependencies)
    if action in {"reference_manifest", "references.manifest"}:
        return 200, reference_manifest()

    if action == "overview":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return 200, overview_payload(data_root, workspace_id, actor, dependencies)
    if action == "pairing.start":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return pairing_start(data_root, workspace_id, actor, payload)
    if action == "pairing.complete":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return pairing_complete(data_root, workspace_id, actor, payload)
    if action == "pairing.status":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return pairing_status(data_root, workspace_id, actor, payload)
    if action == "devices.list":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return 200, devices_list(data_root, workspace_id, actor, payload)
    if action == "devices.revoke":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return devices_revoke(data_root, workspace_id, actor, payload)
    if action == "settings.get":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return 200, settings_get(data_root, workspace_id, actor)
    if action == "settings.update":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return settings_update(data_root, workspace_id, actor, payload)

    return error_payload(
        400,
        "unsupported_action",
        f"Unsupported Senses Phase 1 action `{action}`.",
        allowed_actions=list(DECLARED_BACKEND_ACTIONS),
        deferred_actions=list(DEFERRED_ACTIONS),
    )


def normalize_action(value: object) -> str:
    return str(value or "manifest").strip() or "manifest"


def workspace_id_from_payload(payload: dict[str, object]) -> str | None:
    value = payload.get("_workspace_id") or payload.get("workspace_id")
    try:
        return require_workspace_id(str(value) if value is not None else None)
    except ValueError:
        return None


def actor_from_payload(payload: dict[str, object]) -> dict[str, str | None]:
    raw_actor = payload.get("_app_actor")
    actor = raw_actor if isinstance(raw_actor, dict) else {}
    return {
        "user_id": text_or_none(actor.get("user_id") or payload.get("user_id")),
        "workspace_role": text_or_none(actor.get("workspace_role") or payload.get("workspace_role")),
        "platform_role": text_or_none(actor.get("platform_role") or payload.get("platform_role")),
        "effective_mode": text_or_none(actor.get("effective_mode") or payload.get("effective_mode")),
    }


def require_authenticated(actor: dict[str, str | None]) -> tuple[int, dict[str, object]] | None:
    if actor.get("user_id"):
        return None
    return error_payload(
        401,
        "authentication_required",
        "Senses Phase 1 actions require a Maverick user session.",
    )


def actor_is_manager(actor: dict[str, str | None]) -> bool:
    return str(actor.get("platform_role") or "").lower() in ADMIN_PLATFORM_ROLES or str(
        actor.get("workspace_role") or ""
    ).lower() in ADMIN_WORKSPACE_ROLES


def manifest_payload(
    *,
    workspace_id: str,
    dependencies: dict[str, object],
    actor: dict[str, str | None],
) -> dict[str, object]:
    return {
        "ok": True,
        "app_id": APP_ID,
        "name": APP_NAME,
        "version": APP_VERSION,
        "phase": PHASE,
        "workspace_id": workspace_id,
        "schema_version": SCHEMA_VERSION,
        "auth": {
            "mode": "user_session_mvp",
            "authenticated": bool(actor.get("user_id")),
            "management_role": "workspace_admin",
            "device_token_ingress": False,
        },
        "declared_surfaces": {
            "backend": True,
            "cli": ["senses"],
            "mcp": [
                "senses_operations_manifest",
                "senses_reference_manifest",
            ],
            "frontend": True,
            "reference_entities": [],
            "skills": [],
        },
        "backend_actions": list(DECLARED_BACKEND_ACTIONS),
        "required_dependencies": list(REQUIRED_DEPENDENCIES),
        "dependency_resolution": dependencies,
        "deferred_to_later_phases": list(DEFERRED_ACTIONS),
        "notes": [
            "Senses Phase 1 uses Maverick user sessions for pairing and device registry operations.",
            "Device-token ingress, frame ingestion, and routing remain deferred.",
        ],
    }


def health_action_payload(data_root: Path, workspace_id: str, dependencies: dict[str, object]) -> dict[str, object]:
    return {
        "ok": dependencies["status"] == "resolved",
        "app_id": APP_ID,
        "phase": PHASE,
        "status": "ready" if dependencies["status"] == "resolved" else "dependency_resolution_pending",
        "workspace_id": workspace_id,
        "storage": health_payload(data_root, workspace_id),
        "dependencies": dependencies,
    }


def overview_payload(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
) -> dict[str, object]:
    return {
        "ok": True,
        "app_id": APP_ID,
        "phase": PHASE,
        "workspace_id": workspace_id,
        "actor": public_actor(actor),
        "management": {"can_manage_workspace_devices": actor_is_manager(actor)},
        "settings": settings_payload(data_root, workspace_id),
        "devices": list_devices(data_root, workspace_id, actor, include_all=actor_is_manager(actor)),
        "pairing_sessions": list_pairing_sessions(data_root, workspace_id, actor),
        "dependencies": dependencies,
    }


def pairing_start(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    settings = settings_payload(data_root, workspace_id)
    if not bool(settings.get("allow_member_pairing")) and not actor_is_manager(actor):
        return error_payload(
            403,
            "senses_permission_forbidden",
            "Senses pairing is restricted to workspace admins by current settings.",
        )
    ttl_seconds = bounded_int(
        payload.get("ttl_seconds"),
        default=int(settings.get("pairing_code_ttl_seconds") or 600),
        minimum=PAIRING_TTL_MIN_SECONDS,
        maximum=PAIRING_TTL_MAX_SECONDS,
    )
    device_display_name = bounded_text(payload.get("device_display_name") or payload.get("display_name"), fallback="")
    device_kind = bounded_text(payload.get("device_kind"), fallback="ios", max_length=64)
    platform = bounded_text(payload.get("platform"), fallback="ios", max_length=64)
    metadata = metadata_payload(payload.get("metadata"))
    created_at = now_timestamp()
    expires_at = (datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)).isoformat()
    pairing_id = prefixed_id("pair")
    actor_user_id = str(actor["user_id"])

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        expire_pairing_sessions(db, workspace_id)
        code = insert_pairing_session(
            db,
            workspace_id=workspace_id,
            pairing_id=pairing_id,
            created_by_user_id=actor_user_id,
            device_display_name=device_display_name,
            device_kind=device_kind,
            platform=platform,
            metadata=metadata,
            expires_at=expires_at,
            created_at=created_at,
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="pairing.started",
            actor_user_id=actor_user_id,
            pairing_id=pairing_id,
            details={"expires_at": expires_at, "device_kind": device_kind, "platform": platform},
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM pairing_sessions WHERE workspace_id = ? AND pairing_id = ?",
            (workspace_id, pairing_id),
        ).fetchone()
    finally:
        db.close()
    pairing = pairing_payload(row)
    pairing["code"] = code
    pairing["qr_payload"] = {
        "type": "maverick.senses.pairing",
        "version": 1,
        "app_id": APP_ID,
        "workspace_id": workspace_id,
        "pairing_id": pairing_id,
        "code": code,
        "expires_at": expires_at,
        "backend_action": "pairing.complete",
    }
    pairing["expires_in_seconds"] = ttl_seconds
    return 201, {"ok": True, "pairing": pairing}


def pairing_complete(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    code = normalize_pairing_code(payload.get("code") or payload.get("pairing_code"))
    if not code:
        return error_payload(400, "missing_pairing_code", "pairing.complete requires a pairing code.")
    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    display_name = bounded_text(
        payload.get("device_display_name")
        or payload.get("display_name")
        or payload.get("device_name")
        or payload.get("name"),
        fallback="Senses iOS Device",
        max_length=96,
    )
    device_kind = bounded_text(payload.get("device_kind"), fallback="ios", max_length=64)
    platform = bounded_text(payload.get("platform"), fallback="ios", max_length=64)
    metadata = metadata_payload(payload.get("metadata"))
    for key in ("client_device_id", "app_version", "system_name", "system_version", "model"):
        value = text_or_none(payload.get(key))
        if value:
            metadata[key] = value

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        expire_pairing_sessions(db, workspace_id)
        pairing = db.execute(
            """
            SELECT * FROM pairing_sessions
            WHERE workspace_id = ? AND code_hash = ? AND status = 'pending'
            """,
            (workspace_id, pairing_code_hash(workspace_id, code)),
        ).fetchone()
        if pairing is None:
            db.commit()
            return error_payload(
                404,
                "invalid_or_expired_pairing_code",
                "The pairing code is invalid, expired, or already completed.",
            )
        if pairing_expired(pairing):
            db.execute(
                """
                UPDATE pairing_sessions
                SET status = 'expired'
                WHERE workspace_id = ? AND pairing_id = ?
                """,
                (workspace_id, pairing["pairing_id"]),
            )
            db.commit()
            return error_payload(410, "pairing_code_expired", "The pairing code has expired.")

        device_id = prefixed_id("dev")
        device_session_id = prefixed_id("dvs")
        pairing_id = str(pairing["pairing_id"])
        claim = db.execute(
            """
            UPDATE pairing_sessions
            SET status = 'completed',
                completed_by_user_id = ?,
                device_id = ?,
                device_display_name = ?,
                device_kind = ?,
                platform = ?,
                metadata_json = ?,
                completed_at = ?
            WHERE workspace_id = ? AND pairing_id = ? AND status = 'pending'
            """,
            (
                actor_user_id,
                device_id,
                display_name,
                device_kind,
                platform,
                encode_json_object(metadata),
                timestamp,
                workspace_id,
                pairing_id,
            ),
        )
        if claim.rowcount != 1:
            db.rollback()
            return error_payload(
                404,
                "invalid_or_expired_pairing_code",
                "The pairing code is invalid, expired, or already completed.",
            )
        db.execute(
            """
            INSERT INTO devices(
              workspace_id, device_id, owner_user_id, display_name, device_kind, platform,
              status, pairing_id, metadata_json, paired_at, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                device_id,
                actor_user_id,
                display_name,
                device_kind,
                platform,
                pairing_id,
                encode_json_object(metadata),
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        db.execute(
            """
            INSERT INTO device_sessions(
              workspace_id, device_session_id, device_id, user_id, auth_mode, status,
              created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 'user_session_mvp', 'active', ?, ?)
            """,
            (workspace_id, device_session_id, device_id, actor_user_id, timestamp, timestamp),
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="device.paired",
            actor_user_id=actor_user_id,
            device_id=device_id,
            pairing_id=pairing_id,
            details={"auth_mode": "user_session_mvp", "device_kind": device_kind, "platform": platform},
        )
        db.commit()
        device = db.execute(
            "SELECT * FROM devices WHERE workspace_id = ? AND device_id = ?",
            (workspace_id, device_id),
        ).fetchone()
        device_session = db.execute(
            "SELECT * FROM device_sessions WHERE workspace_id = ? AND device_session_id = ?",
            (workspace_id, device_session_id),
        ).fetchone()
        completed_pairing = db.execute(
            "SELECT * FROM pairing_sessions WHERE workspace_id = ? AND pairing_id = ?",
            (workspace_id, pairing_id),
        ).fetchone()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 200, {
        "ok": True,
        "device": device_payload(device, actor=actor),
        "device_session": device_session_payload(device_session),
        "pairing": pairing_payload(completed_pairing),
    }


def pairing_status(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    pairing_id = text_or_none(payload.get("pairing_id"))
    code = normalize_pairing_code(payload.get("code") or payload.get("pairing_code"))
    if not pairing_id and not code:
        return error_payload(400, "missing_pairing_selector", "pairing.status requires pairing_id or code.")
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        expire_pairing_sessions(db, workspace_id)
        if pairing_id:
            row = db.execute(
                "SELECT * FROM pairing_sessions WHERE workspace_id = ? AND pairing_id = ?",
                (workspace_id, pairing_id),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM pairing_sessions WHERE workspace_id = ? AND code_hash = ?",
                (workspace_id, pairing_code_hash(workspace_id, code)),
            ).fetchone()
        db.commit()
    finally:
        db.close()
    if row is None:
        return error_payload(404, "pairing_not_found", "No matching Senses pairing session was found.")
    if not actor_can_access_pairing(actor, row):
        return error_payload(403, "senses_permission_forbidden", "You cannot inspect this Senses pairing session.")
    return 200, {"ok": True, "pairing": pairing_payload(row)}


def devices_list(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> dict[str, object]:
    include_all = bool(payload.get("include_all")) and actor_is_manager(actor)
    status_filter = text_or_none(payload.get("status"))
    return {
        "ok": True,
        "devices": list_devices(data_root, workspace_id, actor, include_all=include_all, status_filter=status_filter),
        "management": {"can_manage_workspace_devices": actor_is_manager(actor), "include_all": include_all},
    }


def devices_revoke(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    device_id = text_or_none(payload.get("device_id"))
    if not device_id:
        return error_payload(400, "missing_device_id", "devices.revoke requires device_id.")
    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        device = db.execute(
            "SELECT * FROM devices WHERE workspace_id = ? AND device_id = ?",
            (workspace_id, device_id),
        ).fetchone()
        if device is None:
            return error_payload(404, "device_not_found", "No matching Senses device was found.")
        if not actor_is_manager(actor) and str(device["owner_user_id"]) != actor_user_id:
            return error_payload(403, "senses_permission_forbidden", "You cannot revoke this Senses device.")
        db.execute(
            """
            UPDATE devices
            SET status = 'revoked',
                revoked_at = COALESCE(revoked_at, ?),
                revoked_by_user_id = COALESCE(revoked_by_user_id, ?),
                updated_at = ?
            WHERE workspace_id = ? AND device_id = ?
            """,
            (timestamp, actor_user_id, timestamp, workspace_id, device_id),
        )
        db.execute(
            """
            UPDATE device_sessions
            SET status = 'revoked',
                revoked_at = COALESCE(revoked_at, ?),
                revoked_by_user_id = COALESCE(revoked_by_user_id, ?)
            WHERE workspace_id = ? AND device_id = ? AND status != 'revoked'
            """,
            (timestamp, actor_user_id, workspace_id, device_id),
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="device.revoked",
            actor_user_id=actor_user_id,
            device_id=device_id,
            details={"reason": bounded_text(payload.get("reason"), fallback="", max_length=160)},
        )
        db.commit()
        updated = db.execute(
            "SELECT * FROM devices WHERE workspace_id = ? AND device_id = ?",
            (workspace_id, device_id),
        ).fetchone()
    finally:
        db.close()
    return 200, {"ok": True, "device": device_payload(updated, actor=actor)}


def settings_get(data_root: Path, workspace_id: str, actor: dict[str, str | None]) -> dict[str, object]:
    return {
        "ok": True,
        "settings": settings_payload(data_root, workspace_id),
        "management": {"can_update_settings": actor_is_manager(actor)},
    }


def settings_update(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    current = settings_payload(data_root, workspace_id)
    if bool(current.get("require_admin_for_settings")) and not actor_is_manager(actor):
        return error_payload(
            403,
            "senses_permission_forbidden",
            "Senses settings require workspace admin authority.",
        )

    updates: dict[str, object] = {}
    if "allow_member_pairing" in payload:
        updates["allow_member_pairing"] = 1 if bool(payload.get("allow_member_pairing")) else 0
    if "require_admin_for_settings" in payload:
        updates["require_admin_for_settings"] = 1 if bool(payload.get("require_admin_for_settings")) else 0
    if "pairing_code_ttl_seconds" in payload:
        updates["pairing_code_ttl_seconds"] = bounded_int(
            payload.get("pairing_code_ttl_seconds"),
            default=int(current.get("pairing_code_ttl_seconds") or 600),
            minimum=PAIRING_TTL_MIN_SECONDS,
            maximum=PAIRING_TTL_MAX_SECONDS,
        )
    if "max_frame_bytes" in payload:
        updates["max_frame_bytes"] = bounded_int(payload.get("max_frame_bytes"), default=8388608, minimum=1, maximum=52428800)
    if "max_audio_bytes" in payload:
        updates["max_audio_bytes"] = bounded_int(payload.get("max_audio_bytes"), default=10485760, minimum=1, maximum=52428800)
    if not updates:
        return 200, settings_get(data_root, workspace_id, actor)

    updates["updated_at"] = now_timestamp()
    assignments = ", ".join(f"{column} = ?" for column in updates)
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute(
            f"UPDATE settings SET {assignments} WHERE workspace_id = ?",
            [*updates.values(), workspace_id],
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="settings.updated",
            actor_user_id=str(actor["user_id"]),
            details={"updated_fields": sorted(updates)},
        )
        db.commit()
    finally:
        db.close()
    return 200, settings_get(data_root, workspace_id, actor)


def list_devices(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    *,
    include_all: bool,
    status_filter: str | None = None,
) -> list[dict[str, object]]:
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        expire_pairing_sessions(db, workspace_id)
        params: list[object] = [workspace_id]
        where = ["workspace_id = ?"]
        if not include_all:
            where.append("owner_user_id = ?")
            params.append(actor["user_id"])
        if status_filter:
            where.append("status = ?")
            params.append(status_filter)
        rows = db.execute(
            f"""
            SELECT * FROM devices
            WHERE {" AND ".join(where)}
            ORDER BY updated_at DESC, paired_at DESC
            LIMIT 250
            """,
            params,
        ).fetchall()
        db.commit()
    finally:
        db.close()
    return [device_payload(row, actor=actor) for row in rows]


def list_pairing_sessions(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
) -> list[dict[str, object]]:
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        expire_pairing_sessions(db, workspace_id)
        params: list[object] = [workspace_id]
        where = ["workspace_id = ?", "status = 'pending'"]
        if not actor_is_manager(actor):
            where.append("created_by_user_id = ?")
            params.append(actor["user_id"])
        rows = db.execute(
            f"""
            SELECT * FROM pairing_sessions
            WHERE {" AND ".join(where)}
            ORDER BY created_at DESC
            LIMIT 50
            """,
            params,
        ).fetchall()
        db.commit()
    finally:
        db.close()
    return [pairing_payload(row) for row in rows]


def insert_pairing_session(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    pairing_id: str,
    created_by_user_id: str,
    device_display_name: str,
    device_kind: str,
    platform: str,
    metadata: dict[str, object],
    expires_at: str,
    created_at: str,
) -> str:
    for _attempt in range(5):
        code = generate_pairing_code()
        try:
            db.execute(
                """
                INSERT INTO pairing_sessions(
                  workspace_id, pairing_id, code_hash, status, created_by_user_id,
                  device_display_name, device_kind, platform, metadata_json, expires_at, created_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    pairing_id,
                    pairing_code_hash(workspace_id, code),
                    created_by_user_id,
                    device_display_name,
                    device_kind,
                    platform,
                    encode_json_object(metadata),
                    expires_at,
                    created_at,
                ),
            )
            return code
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("Unable to allocate a unique Senses pairing code.")


def expire_pairing_sessions(db: sqlite3.Connection, workspace_id: str) -> None:
    timestamp = now_timestamp()
    db.execute(
        """
        UPDATE pairing_sessions
        SET status = 'expired'
        WHERE workspace_id = ? AND status = 'pending' AND expires_at <= ?
        """,
        (workspace_id, timestamp),
    )


def write_audit(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    event_type: str,
    actor_user_id: str | None,
    device_id: str | None = None,
    pairing_id: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO audit(
          workspace_id, audit_id, event_type, actor_user_id, device_id, pairing_id, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workspace_id,
            prefixed_id("aud"),
            event_type,
            actor_user_id,
            device_id,
            pairing_id,
            encode_json_object(details or {}),
            now_timestamp(),
        ),
    )


def pairing_payload(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    return {
        "workspace_id": row["workspace_id"],
        "pairing_id": row["pairing_id"],
        "status": row["status"],
        "created_by_user_id": row["created_by_user_id"],
        "completed_by_user_id": row["completed_by_user_id"],
        "device_id": row["device_id"],
        "device_display_name": row["device_display_name"],
        "device_kind": row["device_kind"],
        "platform": row["platform"],
        "metadata": decode_json_object(row["metadata_json"]),
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "revoked_at": row["revoked_at"],
    }


def device_payload(row: sqlite3.Row | None, *, actor: dict[str, str | None]) -> dict[str, object]:
    if row is None:
        return {}
    can_revoke = actor_is_manager(actor) or str(row["owner_user_id"]) == str(actor.get("user_id"))
    return {
        "workspace_id": row["workspace_id"],
        "device_id": row["device_id"],
        "owner_user_id": row["owner_user_id"],
        "display_name": row["display_name"],
        "device_kind": row["device_kind"],
        "platform": row["platform"],
        "status": row["status"],
        "pairing_id": row["pairing_id"],
        "metadata": decode_json_object(row["metadata_json"]),
        "paired_at": row["paired_at"],
        "last_seen_at": row["last_seen_at"],
        "revoked_at": row["revoked_at"],
        "revoked_by_user_id": row["revoked_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "can_revoke": can_revoke and row["status"] != "revoked",
    }


def device_session_payload(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    return {
        "workspace_id": row["workspace_id"],
        "device_session_id": row["device_session_id"],
        "device_id": row["device_id"],
        "user_id": row["user_id"],
        "auth_mode": row["auth_mode"],
        "status": row["status"],
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "revoked_at": row["revoked_at"],
    }


def reference_manifest() -> dict[str, object]:
    return {
        "ok": True,
        "app_id": APP_ID,
        "schema_version": "1",
        "entity_types": [],
        "notes": ["Senses reference search remains deferred until capture records exist."],
    }


def dependency_resolution_payload(raw_dependencies: object) -> dict[str, object]:
    if not isinstance(raw_dependencies, dict) or not isinstance(raw_dependencies.get("dependencies"), list):
        return {
            "status": "unknown",
            "blocked_reason": "dependency_resolution_not_provided_by_host",
            "dependencies": [
                {**dependency, "status": "unknown", "selected_provider_app_ids": []}
                for dependency in REQUIRED_DEPENDENCIES
            ],
        }
    dependencies_by_alias = {
        str(item.get("alias")): item
        for item in raw_dependencies.get("dependencies", [])
        if isinstance(item, dict)
    }
    required = []
    for dependency in REQUIRED_DEPENDENCIES:
        resolved = dependencies_by_alias.get(str(dependency["alias"]))
        if isinstance(resolved, dict):
            required.append(_compact_dependency(resolved))
        else:
            required.append({**dependency, "status": "missing_declaration", "selected_provider_app_ids": []})
    blocked = [item for item in required if str(item.get("status")) not in {"resolved"}]
    return {
        "status": "blocked" if blocked else "resolved",
        "workspace_id": raw_dependencies.get("workspace_id"),
        "consumer_app_id": raw_dependencies.get("consumer_app_id"),
        "dependencies": required,
        "blocked_reason": "; ".join(
            str(item.get("blocked_reason") or item.get("status") or "")
            for item in blocked
            if str(item.get("blocked_reason") or item.get("status") or "").strip()
        ) or None,
    }


def _compact_dependency(item: dict[str, Any]) -> dict[str, object]:
    return {
        "alias": item.get("alias"),
        "interface": item.get("interface"),
        "version": item.get("version"),
        "required": item.get("required"),
        "cardinality": item.get("cardinality"),
        "status": item.get("status"),
        "selected_provider_app_ids": item.get("selected_provider_app_ids") or [],
        "candidate_provider_app_ids": [
            candidate.get("app_id")
            for candidate in item.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("app_id")
        ],
        "blocked_reason": item.get("blocked_reason"),
    }


def app_events_for_action(action: str) -> list[dict[str, str]]:
    normalized = normalize_action(action)
    if normalized == "pairing.complete":
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "pairing"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "devices"},
        ]
    if normalized in {"pairing.start", "pairing.status"}:
        return [{"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "pairing"}]
    if normalized in {"devices.revoke"}:
        return [{"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "devices"}]
    if normalized == "settings.update":
        return [{"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "settings"}]
    return []


def error_payload(status_code: int, error: str, detail: str, **extra: object) -> tuple[int, dict[str, object]]:
    return status_code, {"ok": False, "error": error, "detail": detail, **extra}


def public_actor(actor: dict[str, str | None]) -> dict[str, object]:
    return {
        "authenticated": bool(actor.get("user_id")),
        "user_id": actor.get("user_id"),
        "workspace_role": actor.get("workspace_role"),
        "platform_role": actor.get("platform_role"),
        "can_manage_workspace_devices": actor_is_manager(actor),
    }


def actor_can_access_pairing(actor: dict[str, str | None], row: sqlite3.Row) -> bool:
    if actor_is_manager(actor):
        return True
    user_id = str(actor.get("user_id") or "")
    return user_id in {str(row["created_by_user_id"] or ""), str(row["completed_by_user_id"] or "")}


def pairing_expired(row: sqlite3.Row) -> bool:
    return str(row["expires_at"]) <= now_timestamp()


def generate_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))


def normalize_pairing_code(value: object) -> str:
    return "".join(char for char in str(value or "").upper().strip() if char.isalnum())


def pairing_code_hash(workspace_id: str, code: str) -> str:
    normalized = normalize_pairing_code(code)
    return hashlib.sha256(f"{workspace_id}:{normalized}".encode("utf-8")).hexdigest()


def prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def bounded_text(value: object, *, fallback: str, max_length: int = 128) -> str:
    text = text_or_none(value) or fallback
    return text[:max_length]


def bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def metadata_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    metadata: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            metadata[key[:64]] = item
    return metadata
