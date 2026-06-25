"""Phase 8 service layer for Senses."""

from __future__ import annotations

from base64 import b64decode, b64encode
import binascii
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import string
from typing import Any
import uuid
import zlib

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
APP_VERSION = "0.8.0"
PHASE = "phase-8"
VIEW_STATE_FILENAME = "view_state.json"
PAIRING_CODE_ALPHABET = "".join(char for char in string.ascii_uppercase + string.digits if char not in {"0", "O", "I", "1"})
PAIRING_CODE_LENGTH = 8
PAIRING_TTL_MIN_SECONDS = 60
PAIRING_TTL_MAX_SECONDS = 3600
ADMIN_WORKSPACE_ROLES = {"admin"}
ADMIN_PLATFORM_ROLES = {"admin"}
CAPTURE_REQUEST_SCHEMA_VERSION = "senses.capture.v1"
CAPTURE_ACCEPTED_SCHEMA_VERSION = "senses.capture.accepted.v1"
AUDIO_CAPTURE_REQUEST_SCHEMA_VERSION = "senses.audio.v1"
AUDIO_ACCEPTED_SCHEMA_VERSION = "senses.audio.accepted.v1"
BUNDLE_REQUEST_SCHEMA_VERSION = "senses.bundle.v1"
BUNDLE_ACCEPTED_SCHEMA_VERSION = "senses.bundle.accepted.v1"
BUNDLE_PART_ACCEPTED_SCHEMA_VERSION = "senses.bundle_part.accepted.v1"
BUNDLE_DISPATCH_SCHEMA_VERSION = "senses.bundle.dispatch.v1"
CAPTURE_CLOCK_SKEW_SECONDS = 600
FRAME_RATE_LIMIT_WINDOW_SECONDS = 60
FRAME_RATE_LIMIT_MAX = 30
MAX_AUDIO_DURATION_SECONDS = 60
MIN_AUDIO_BYTES = 128
BUNDLE_ITEM_ROLES = {"frame", "audio"}
SUPPORTED_FRAME_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
SUPPORTED_AUDIO_CONTENT_TYPES = {
    "audio/aac": ".aac",
    "audio/m4a": ".m4a",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
}
CAPTURE_CONTENT_TYPE_EXTENSIONS = {
    **SUPPORTED_FRAME_CONTENT_TYPES,
    **SUPPORTED_AUDIO_CONTENT_TYPES,
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_START_OF_FRAME_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}
JPEG_METADATA_MARKERS = {0xE1, 0xED, 0xFE}
PNG_COLOR_TYPE_SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
PNG_ALLOWED_BIT_DEPTHS = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}
PNG_CRITICAL_CHUNK_TYPES = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
PNG_MAX_DIMENSION = 100_000
PNG_MAX_DECOMPRESSED_BYTES = 100_000_000
STORAGE_WRITE_DEPENDENCY_ALIAS = "storage-file-content-write"
CHAT_COMMUNICATION_DEPENDENCY_ALIAS = "chat-communication"
SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS = "speech-to-text"
SPEECH_SYNTHESIS_DEPENDENCY_ALIAS = "text-to-speech"
STORAGE_PENDING_LEASE_SECONDS = 120
TRANSCRIPTION_SUBMITTED_LEASE_SECONDS = 180
BACKGROUND_TRANSCRIPTION_BATCH_SIZE = 3
DEFAULT_RUNTIME_AGENT_ID = "chat"
RUNTIME_DISPATCH_CALLBACK_ACTION = "runtime_dispatch.completed"
SPEECH_TRANSCRIPTION_CALLBACK_ACTION = "speech_transcription.completed"
FOLLOWUP_ROUTE_WINDOW_SECONDS_MIN = 15
FOLLOWUP_ROUTE_WINDOW_SECONDS_MAX = 3600
LONG_TASK_PROMPT_LENGTH = 180
LONG_TASK_KEYWORDS = (
    "analizza",
    "analysis",
    "approfondisci",
    "cerca",
    "confronta",
    "debug",
    "implementa",
    "pianifica",
    "prepara",
    "ricerca",
    "riassumi",
    "scrivi",
)
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
OPTIONAL_DEPENDENCIES = (
    {
        "alias": CHAT_COMMUNICATION_DEPENDENCY_ALIAS,
        "interface": "communication.chat",
        "version": "^1",
        "required": False,
    },
    {
        "alias": SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS,
        "interface": "speech.transcription",
        "version": "^1",
        "required": False,
    },
    {
        "alias": SPEECH_SYNTHESIS_DEPENDENCY_ALIAS,
        "interface": "speech.synthesis",
        "version": "^1",
        "required": False,
    },
)
DECLARED_DEPENDENCIES = (*REQUIRED_DEPENDENCIES, *OPTIONAL_DEPENDENCIES)
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
    "captures.get",
    "captures.bundle_get",
    "ingest.bundle.start",
    "ingest.bundle_part",
    "ingest.frame",
    "ingest.audio",
    "routing.dispatch_bundle",
    "routing.dispatch_capture",
    "routing.reset",
    "view_filter",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
)
DECLARED_MCP_TOOLS = (
    "senses_reference_manifest",
    "senses_operations_manifest",
    "senses_view_filter",
    "senses_set_view_filter",
    "senses_set_custom_view",
    "senses_clear_custom_view",
)
VIEW_STATE_ACTIONS = ("view_filter", "set_view_filter", "set_custom_view", "clear_custom_view")
VIEW_STATE_MUTATION_ACTIONS = ("set_view_filter", "set_custom_view", "clear_custom_view")
CALLBACK_BACKEND_ACTIONS = ("storage_write.completed", SPEECH_TRANSCRIPTION_CALLBACK_ACTION, RUNTIME_DISPATCH_CALLBACK_ACTION)
DEFERRED_ACTIONS = (
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
    if action in VIEW_STATE_ACTIONS:
        auth_error = require_view_state_authority(actor, action)
        if auth_error is not None:
            return auth_error
        return view_state_action(data_root, workspace_id, action, payload)
    if action == "storage_write.completed":
        return storage_write_completed(data_root, workspace_id, dependencies, payload)
    if action == SPEECH_TRANSCRIPTION_CALLBACK_ACTION:
        return speech_transcription_completed(data_root, workspace_id, dependencies, payload)
    if action == RUNTIME_DISPATCH_CALLBACK_ACTION:
        return runtime_dispatch_completed(data_root, workspace_id, dependencies, payload)

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
    if action == "captures.get":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return captures_get(data_root, workspace_id, actor, dependencies, payload)
    if action == "captures.bundle_get":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return captures_bundle_get(data_root, workspace_id, actor, dependencies, payload)
    if action == "ingest.bundle.start":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return ingest_bundle_start(data_root, workspace_id, actor, payload)
    if action == "ingest.bundle_part":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return ingest_bundle_part(data_root, workspace_id, actor, dependencies, payload)
    if action == "ingest.frame":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return ingest_frame(data_root, workspace_id, actor, dependencies, payload)
    if action == "ingest.audio":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return ingest_audio(data_root, workspace_id, actor, dependencies, payload)
    if action == "routing.dispatch_capture":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return routing_dispatch_capture(data_root, workspace_id, actor, dependencies, payload)
    if action == "routing.dispatch_bundle":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return routing_dispatch_bundle(data_root, workspace_id, actor, dependencies, payload)
    if action == "routing.reset":
        auth_error = require_authenticated(actor)
        if auth_error is not None:
            return auth_error
        return routing_reset(data_root, workspace_id, actor, dependencies, payload)

    return error_payload(
        400,
        "unsupported_action",
        f"Unsupported Senses Phase 8 action `{action}`.",
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
        "Senses Phase 8 actions require a Maverick user session.",
    )


def require_view_state_authority(
    actor: dict[str, str | None],
    action: str,
) -> tuple[int, dict[str, object]] | None:
    auth_error = require_authenticated(actor)
    if auth_error is not None:
        return auth_error
    if action in VIEW_STATE_MUTATION_ACTIONS and not actor_is_manager(actor):
        return error_payload(
            403,
            "senses_permission_forbidden",
            "Mutating Senses shared view state requires workspace admin authority.",
        )
    return None


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
    available = dependencies["status"] == "resolved"
    return {
        "ok": available,
        "action": "manifest",
        "available": available,
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
            "user_session_ingest_supported": True,
            "user_session_audio_ingest_supported": True,
            "raw_device_auth_supported": False,
            "view_state_policy": {
                "scope": "workspace_shared",
                "read": "authenticated_user",
                "mutate": "workspace_admin",
            },
        },
        "declared_surfaces": {
            "backend": True,
            "cli": ["senses"],
            "mcp": list(DECLARED_MCP_TOOLS),
            "frontend": True,
            "reference_entities": [],
            "skills": [],
        },
        "backend_actions": list(DECLARED_BACKEND_ACTIONS),
        "callback_actions": list(CALLBACK_BACKEND_ACTIONS),
        "audio_mvp": {
            "push_to_talk": True,
            "continuous_streaming": False,
            "max_duration_seconds": MAX_AUDIO_DURATION_SECONDS,
            "supported_content_types": sorted(SUPPORTED_AUDIO_CONTENT_TYPES),
            "speech_to_text_dependency_alias": SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS,
            "text_to_speech_dependency_alias": SPEECH_SYNTHESIS_DEPENDENCY_ALIAS,
        },
        "required_dependencies": list(REQUIRED_DEPENDENCIES),
        "optional_dependencies": list(OPTIONAL_DEPENDENCIES),
        "dependency_resolution": dependencies,
        "deferred_to_later_phases": list(DEFERRED_ACTIONS),
        "notes": [
            "Senses Phase 8 uses Maverick user sessions for pairing, device registry, frame/audio ingestion, routing, and the workspace frontend.",
            "ingest.frame is available with a Maverick user session and active device_session_id.",
            "ingest.audio accepts bounded push-to-talk audio, writes Storage, and uses Speech transcription when the optional dependency is resolved.",
            "ingest.bundle.start and ingest.bundle_part group one frame plus one audio capture for a single multimodal dispatch.",
            "ingest.frame stores captures through the declared Storage dependency and never launches runtime turns.",
            "routing.dispatch_capture emits runtime_launch_requests only after a capture is stored.",
            "routing.dispatch_bundle emits one runtime request only after the frame, audio file, and non-empty transcript are ready.",
            "Raw device auth remains deferred.",
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
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
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
        "captures": list_captures(
            data_root,
            workspace_id,
            actor,
            include_all=actor_is_manager(actor),
            chat_provider_app_id=chat_provider_app_id,
        ),
        "capture_bundles": list_capture_bundles(
            data_root,
            workspace_id,
            actor,
            include_all=actor_is_manager(actor),
            chat_provider_app_id=chat_provider_app_id,
        ),
        "routing_sessions": list_routing_sessions(
            data_root,
            workspace_id,
            actor,
            include_all=actor_is_manager(actor),
            chat_provider_app_id=chat_provider_app_id,
        ),
        "dependencies": dependencies,
    }


def view_state_action(
    data_root: Path,
    workspace_id: str,
    action: str,
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    state = load_view_state(data_root, workspace_id)
    if action == "view_filter":
        return 200, {"ok": True, "state": state}

    if action == "set_view_filter":
        current = state.get("view_filter") if isinstance(state.get("view_filter"), dict) else {}
        updates = payload.get("view_filter") if isinstance(payload.get("view_filter"), dict) else payload
        state["view_filter"] = {
            **current,
            **compact_view_filter(updates),
            "updated_at": now_timestamp(),
        }
    elif action == "set_custom_view":
        state["custom_view"] = compact_custom_view(payload)
        state["view_filter"] = {
            **(state.get("view_filter") if isinstance(state.get("view_filter"), dict) else {}),
            "updated_at": now_timestamp(),
        }
    elif action == "clear_custom_view":
        state["custom_view"] = None
        state["view_filter"] = {
            **(state.get("view_filter") if isinstance(state.get("view_filter"), dict) else {}),
            "updated_at": now_timestamp(),
        }
    else:
        return error_payload(400, "unsupported_action", f"Unsupported Senses view-state action `{action}`.")

    save_view_state(data_root, workspace_id, state)
    return 200, {"ok": True, "state": state}


def load_view_state(data_root: Path, workspace_id: str) -> dict[str, object]:
    path = view_state_path(data_root)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict) or payload.get("workspace_id") != workspace_id:
        return default_view_state(workspace_id)
    return {
        **default_view_state(workspace_id),
        **payload,
    }


def save_view_state(data_root: Path, workspace_id: str, state: dict[str, object]) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    path = view_state_path(data_root)
    payload = {
        **default_view_state(workspace_id),
        **state,
        "workspace_id": workspace_id,
        "schema_version": "1",
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def default_view_state(workspace_id: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "workspace_id": workspace_id,
        "view_filter": {
            "tab": "devices",
            "query": "",
            "capture_filter": "all",
            "routing_filter": "all",
            "updated_at": None,
        },
        "custom_view": None,
    }


def view_state_path(data_root: Path) -> Path:
    return data_root / VIEW_STATE_FILENAME


def compact_view_filter(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, object] = {}
    for key in ("tab", "query", "status", "capture_filter", "routing_filter", "device_id", "capture_id"):
        value = text_or_none(payload.get(key))
        if value is not None:
            result[key] = bounded_text(value, fallback="", max_length=128)
    return result


def compact_custom_view(payload: dict[str, object]) -> dict[str, object]:
    refs = payload.get("refs")
    compact_refs: list[object] = []
    if isinstance(refs, list):
        compact_refs = refs[:100]
    return {
        "title": bounded_text(payload.get("title"), fallback="Custom view", max_length=120),
        "refs": compact_refs,
        "updated_at": now_timestamp(),
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
        settings_row = db.execute(
            "SELECT allow_member_pairing FROM settings WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        allow_member_pairing = bool(settings_row["allow_member_pairing"]) if settings_row is not None else True
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
        if not pairing_completion_allowed(allow_member_pairing=allow_member_pairing, actor=actor, row=pairing):
            db.commit()
            return error_payload(
                403,
                "senses_permission_forbidden",
                "Senses pairing completion is restricted to workspace admins or the user who created this code.",
            )

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
    if "routing_followup_window_seconds" in payload:
        updates["routing_followup_window_seconds"] = bounded_int(
            payload.get("routing_followup_window_seconds"),
            default=int(current.get("routing_followup_window_seconds") or 300),
            minimum=FOLLOWUP_ROUTE_WINDOW_SECONDS_MIN,
            maximum=FOLLOWUP_ROUTE_WINDOW_SECONDS_MAX,
        )
    if "default_retention_class" in payload:
        updates["default_retention_class"] = bounded_text(
            payload.get("default_retention_class"),
            fallback=str(current.get("default_retention_class") or "chat_attachment"),
            max_length=64,
        )
    if "failed_capture_ttl_seconds" in payload:
        updates["failed_capture_ttl_seconds"] = bounded_int(
            payload.get("failed_capture_ttl_seconds"),
            default=int(current.get("failed_capture_ttl_seconds") or 86400),
            minimum=60,
            maximum=2_592_000,
        )
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


def ingest_frame(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    if dependencies["status"] != "resolved":
        return error_payload(
            503,
            "dependency_unavailable",
            "Senses requires the Storage write dependency before accepting frame ingestion.",
            dependencies=dependencies,
        )

    settings = settings_payload(data_root, workspace_id)
    prepared, validation_error = prepare_capture_payload(payload, settings)
    if validation_error is not None:
        return validation_error

    device_id = str(prepared["device_id"])
    device_session_id = str(prepared["device_session_id"])
    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    dependency_request: dict[str, object] | None = None
    try:
        db.execute("BEGIN IMMEDIATE")
        auth_error = validate_device_for_ingest(
            db,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            device_id=device_id,
            device_session_id=device_session_id,
        )
        if auth_error is not None:
            db.rollback()
            return auth_error

        existing = db.execute(
            """
            SELECT * FROM ingestion_requests
            WHERE workspace_id = ? AND device_id = ? AND idempotency_key = ?
            """,
            (workspace_id, device_id, prepared["idempotency_key"]),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != str(prepared["request_hash"]):
                db.rollback()
                return error_payload(
                    409,
                    "idempotency_conflict",
                    "The idempotency_key was already used for a different Senses capture payload.",
                )
            capture = capture_by_id(db, workspace_id, str(existing["capture_id"] or ""))
            if capture is None:
                db.rollback()
                return error_payload(
                    500,
                    "storage_write_failed",
                    "Senses ingestion state is missing the capture record for this idempotency key.",
                )
            capture_status = str(capture["status"])
            if capture_status == "storage_failed":
                db.execute(
                    """
                    UPDATE captures
                    SET status = 'storage_pending', error_code = NULL, updated_at = ?
                    WHERE workspace_id = ? AND capture_id = ?
                    """,
                    (timestamp, workspace_id, capture["capture_id"]),
                )
                db.execute(
                    """
                    UPDATE ingestion_requests
                    SET status = 'storage_pending', error_code = NULL, completed_at = NULL
                    WHERE workspace_id = ? AND request_id = ?
                    """,
                    (workspace_id, existing["request_id"]),
                )
                capture = capture_by_id(db, workspace_id, str(capture["capture_id"]))
                dependency_request = storage_write_dependency_request(capture, prepared, reissue=True)
            elif capture_status == "storage_pending" and storage_pending_stale(capture, timestamp):
                db.execute(
                    """
                    UPDATE captures
                    SET error_code = NULL, updated_at = ?
                    WHERE workspace_id = ? AND capture_id = ?
                    """,
                    (timestamp, workspace_id, capture["capture_id"]),
                )
                db.execute(
                    """
                    UPDATE ingestion_requests
                    SET status = 'storage_pending', error_code = NULL, completed_at = NULL
                    WHERE workspace_id = ? AND request_id = ?
                    """,
                    (workspace_id, existing["request_id"]),
                )
                write_audit(
                    db,
                    workspace_id=workspace_id,
                    event_type="capture.storage_write_reissued",
                    actor_user_id=actor_user_id,
                    device_id=device_id,
                    details={
                        "capture_id": capture["capture_id"],
                        "request_id": existing["request_id"],
                        "lease_seconds": STORAGE_PENDING_LEASE_SECONDS,
                    },
                )
                capture = capture_by_id(db, workspace_id, str(capture["capture_id"]))
                dependency_request = storage_write_dependency_request(capture, prepared, reissue=True)
            db.commit()
            response = ingest_acceptance_response(existing, capture)
            if dependency_request is not None:
                response["dependency_backend_requests"] = [dependency_request]
            return 200, response

        rate_error = rate_limit_error(db, workspace_id=workspace_id, device_id=device_id)
        if rate_error is not None:
            db.rollback()
            return rate_error

        capture_id = prefixed_id("cap")
        workspace_relative_path = capture_storage_path(
            device_id=device_id,
            capture_id=capture_id,
            captured_at=prepared["captured_at_datetime"],
            content_type=str(prepared["content_type"]),
        )
        request_id = str(prepared["request_id"])
        db.execute(
            """
            INSERT INTO ingestion_requests(
              workspace_id, request_id, device_id, device_session_id, idempotency_key,
              client_capture_id, capture_id, request_hash, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'storage_pending', ?)
            """,
            (
                workspace_id,
                request_id,
                device_id,
                device_session_id,
                prepared["idempotency_key"],
                prepared["client_capture_id"],
                capture_id,
                prepared["request_hash"],
                timestamp,
            ),
        )
        db.execute(
            """
            INSERT INTO captures(
              workspace_id, capture_id, device_id, device_session_id, ingestion_request_id,
              input_mode, prompt, content_type, workspace_relative_path, sha256, size_bytes,
              width, height, retention_class, status, captured_at, ingested_at,
              metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'storage_pending', ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                capture_id,
                device_id,
                device_session_id,
                request_id,
                prepared["input_mode"],
                prepared["prompt"],
                prepared["content_type"],
                workspace_relative_path,
                prepared["sha256"],
                prepared["size_bytes"],
                prepared["width"],
                prepared["height"],
                settings.get("default_retention_class") or "chat_attachment",
                prepared["captured_at"],
                timestamp,
                encode_json_object(prepared["metadata"]),
                timestamp,
                timestamp,
            ),
        )
        if device_id and device_session_id:
            db.execute(
                "UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE workspace_id = ? AND device_id = ?",
                (timestamp, timestamp, workspace_id, device_id),
            )
            db.execute(
                """
                UPDATE device_sessions
                SET last_seen_at = ?
                WHERE workspace_id = ? AND device_session_id = ?
                """,
                (timestamp, workspace_id, device_session_id),
            )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="capture.accepted",
            actor_user_id=actor_user_id,
            device_id=device_id,
            details={
                "capture_id": capture_id,
                "request_id": request_id,
                "workspace_relative_path": workspace_relative_path,
                "sha256": prepared["sha256"],
                "size_bytes": prepared["size_bytes"],
            },
        )
        db.commit()
        capture = capture_by_id(db, workspace_id, capture_id)
        ingestion_request = db.execute(
            "SELECT * FROM ingestion_requests WHERE workspace_id = ? AND request_id = ?",
            (workspace_id, request_id),
        ).fetchone()
    except sqlite3.IntegrityError:
        db.rollback()
        return error_payload(
            409,
            "idempotency_conflict",
            "Senses could not claim this request_id or idempotency_key because it already exists.",
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    response = ingest_acceptance_response(ingestion_request, capture)
    response["dependency_backend_requests"] = [storage_write_dependency_request(capture, prepared)]
    return 202, response


def ingest_audio(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    status_code, response = ingest_frame(data_root, workspace_id, actor, dependencies, payload)
    if status_code >= 400 or not response.get("ok"):
        return status_code, response

    capture_id = text_or_none(response.get("capture_id"))
    if not capture_id:
        return status_code, response

    speech_provider_app_id = speech_provider_app_id_from_dependencies(dependencies, alias=SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS)
    transcription = transcription_response_payload(
        {"status": "unavailable", "provider_app_id": None, "text": "", "error": None}
    )
    if speech_provider_app_id and status_code == 202:
        transcription_request_id = f"transcribe-{capture_id}"
        mark_capture_transcription_requested(
            data_root,
            workspace_id=workspace_id,
            capture_id=capture_id,
            request_id=transcription_request_id,
            provider_app_id=speech_provider_app_id,
        )
        transcription = transcription_response_payload(
            {
                "status": "pending",
                "request_id": transcription_request_id,
                "provider_app_id": speech_provider_app_id,
                "text": "",
                "error": None,
            }
        )
    elif speech_provider_app_id:
        capture = capture_by_id_from_root(data_root, workspace_id, capture_id)
        transcription = transcription_payload(capture)

    response["schema_version"] = AUDIO_ACCEPTED_SCHEMA_VERSION
    response["transcription"] = transcription
    return status_code, response


def ingest_bundle_start(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    schema_version = text_or_none(payload.get("schema_version"))
    if schema_version not in {None, BUNDLE_REQUEST_SCHEMA_VERSION}:
        return error_payload(
            400,
            "invalid_schema_version",
            f"ingest.bundle.start requires schema_version `{BUNDLE_REQUEST_SCHEMA_VERSION}` when supplied.",
        )
    bundle_id = bounded_identifier(payload.get("bundle_id"), max_length=160)
    request_id = bounded_identifier(payload.get("request_id"), max_length=160)
    if not bundle_id:
        return error_payload(400, "invalid_bundle_id", "ingest.bundle.start requires bundle_id.")
    if not request_id:
        return error_payload(400, "invalid_request_id", "ingest.bundle.start requires request_id.")
    device_id = bounded_identifier(payload.get("device_id"), max_length=128)
    device_session_id = bounded_identifier(payload.get("device_session_id"), max_length=128)
    if bool(device_id) != bool(device_session_id):
        return error_payload(
            400,
            "invalid_device",
            "ingest.bundle.start requires both device_id and device_session_id when either is supplied.",
        )
    stored_device_id = device_id or None
    stored_device_session_id = device_session_id or None

    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    metadata = metadata_payload(payload.get("metadata"))
    prompt = bounded_text(payload.get("prompt"), fallback="", max_length=2048)

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        if device_id and device_session_id:
            auth_error = validate_device_for_ingest(
                db,
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                device_id=device_id,
                device_session_id=device_session_id,
            )
            if auth_error is not None:
                db.rollback()
                return auth_error

        existing = bundle_by_id(db, workspace_id, bundle_id)
        if existing is not None:
            if (
                str(existing["request_id"]) != request_id
                or (text_or_none(existing["device_id"]) or "") != (device_id or "")
                or str(existing["user_id"]) != actor_user_id
            ):
                db.rollback()
                return error_payload(
                    409,
                    "bundle_conflict",
                    "bundle_id is already associated with a different Senses bundle request.",
                )
            db.commit()
            return 200, bundle_action_response(
                existing,
                bundle_items_with_captures(db, workspace_id, bundle_id),
                chat_provider_app_id=None,
            )

        request_conflict = db.execute(
            """
            SELECT * FROM capture_bundles
            WHERE workspace_id = ? AND request_id = ?
            """,
            (workspace_id, request_id),
        ).fetchone()
        if request_conflict is not None:
            db.rollback()
            return error_payload(
                409,
                "bundle_conflict",
                "request_id is already associated with a different Senses bundle.",
            )

        db.execute(
            """
            INSERT INTO capture_bundles(
              workspace_id, bundle_id, request_id, user_id, device_id, device_session_id,
              status, prompt, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'started', ?, ?, ?, ?)
            """,
            (
                workspace_id,
                bundle_id,
                request_id,
                actor_user_id,
                stored_device_id,
                stored_device_session_id,
                prompt,
                encode_json_object(metadata),
                timestamp,
                timestamp,
            ),
        )
        if device_id and device_session_id:
            db.execute(
                "UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE workspace_id = ? AND device_id = ?",
                (timestamp, timestamp, workspace_id, device_id),
            )
            db.execute(
                """
                UPDATE device_sessions
                SET last_seen_at = ?
                WHERE workspace_id = ? AND device_session_id = ?
                """,
                (timestamp, workspace_id, device_session_id),
            )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="bundle.started",
            actor_user_id=actor_user_id,
            device_id=device_id,
            details={"bundle_id": bundle_id, "request_id": request_id},
        )
        db.commit()
        bundle = bundle_by_id(db, workspace_id, bundle_id)
    except sqlite3.IntegrityError:
        db.rollback()
        return error_payload(
            409,
            "bundle_conflict",
            "Senses could not claim this bundle_id or request_id because it already exists.",
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 201, bundle_action_response(bundle, [], chat_provider_app_id=None)


def ingest_bundle_part(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    bundle_id = bounded_identifier(payload.get("bundle_id"), max_length=160)
    if not bundle_id:
        return error_payload(400, "invalid_bundle_id", "ingest.bundle_part requires bundle_id.")
    role = normalize_bundle_item_role(payload.get("role"))
    if role is None:
        return error_payload(400, "invalid_bundle_role", "ingest.bundle_part role must be `frame` or `audio`.")

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        bundle = bundle_by_id(db, workspace_id, bundle_id)
        if bundle is None:
            return error_payload(404, "bundle_not_found", "No matching Senses capture bundle was found.")
        if not actor_can_access_bundle(db, workspace_id=workspace_id, actor=actor, bundle=bundle):
            return error_payload(403, "senses_permission_forbidden", "You cannot update this Senses bundle.")
        existing = bundle_item_by_role(db, workspace_id, bundle_id, role)
        if existing is not None:
            capture = capture_by_id(db, workspace_id, str(existing["capture_id"]))
            if capture is None:
                return error_payload(
                    500,
                    "bundle_item_missing_capture",
                    "Senses bundle state is missing the linked capture record.",
                )
            return 200, bundle_part_response(
                bundle,
                bundle_items_with_captures(db, workspace_id, bundle_id),
                existing,
                capture,
                chat_provider_app_id=chat_provider_app_id_from_dependencies(dependencies),
            )
    finally:
        db.close()

    part_payload = bundle_part_capture_payload(payload, role=role, bundle_id=bundle_id)
    bundle_device_id = text_or_none(bundle["device_id"])
    bundle_device_session_id = text_or_none(bundle["device_session_id"])
    part_has_device = bool(text_or_none(part_payload.get("device_id")) and text_or_none(part_payload.get("device_session_id")))
    if not part_has_device and bundle_device_id and bundle_device_session_id:
        part_payload["device_id"] = bundle_device_id
        part_payload["device_session_id"] = bundle_device_session_id
    elif not part_has_device and role == "audio":
        return error_payload(
            409,
            "bundle_device_pending",
            "Senses needs the frame bundle part before audio can inherit the active device session.",
            bundle_id=bundle_id,
        )
    if role == "audio":
        status_code, response = ingest_audio(data_root, workspace_id, actor, dependencies, part_payload)
    else:
        status_code, response = ingest_frame(data_root, workspace_id, actor, dependencies, part_payload)
    if status_code >= 400 or not response.get("ok"):
        return status_code, response

    capture_id = text_or_none(response.get("capture_id"))
    request_id = text_or_none(response.get("request_id"))
    if not capture_id:
        return error_payload(500, "invalid_bundle_part", "Senses accepted a bundle part without capture_id.")

    timestamp = now_timestamp()
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        bundle = bundle_by_id(db, workspace_id, bundle_id)
        if bundle is None:
            db.rollback()
            return error_payload(404, "bundle_not_found", "No matching Senses capture bundle was found.")
        if not actor_can_access_bundle(db, workspace_id=workspace_id, actor=actor, bundle=bundle):
            db.rollback()
            return error_payload(403, "senses_permission_forbidden", "You cannot update this Senses bundle.")
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            db.rollback()
            return error_payload(404, "capture_not_found", "No matching Senses capture was found.")
        existing = bundle_item_by_role(db, workspace_id, bundle_id, role)
        if existing is not None and str(existing["capture_id"]) != capture_id:
            db.rollback()
            return error_payload(
                409,
                "bundle_part_conflict",
                f"Senses bundle already has a different `{role}` part.",
            )
        if existing is None:
            db.execute(
                """
                INSERT INTO capture_bundle_items(
                  workspace_id, bundle_id, role, capture_id, request_id, status, metadata_json,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    bundle_id,
                    role,
                    capture_id,
                    request_id,
                    capture["status"],
                    encode_json_object({"source_action": payload.get("action")}),
                    timestamp,
                    timestamp,
                ),
            )
        else:
            db.execute(
                """
                UPDATE capture_bundle_items
                SET status = ?, error_code = ?, updated_at = ?
                WHERE workspace_id = ? AND bundle_id = ? AND role = ?
                """,
                (capture["status"], capture["error_code"], timestamp, workspace_id, bundle_id, role),
            )
        if not text_or_none(bundle["device_id"]):
            db.execute(
                """
                UPDATE capture_bundles
                SET device_id = ?,
                    device_session_id = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND bundle_id = ?
                """,
                (
                    capture["device_id"],
                    capture["device_session_id"],
                    timestamp,
                    workspace_id,
                    bundle_id,
                ),
            )
        update_bundle_status_from_items(db, workspace_id=workspace_id, bundle_id=bundle_id, timestamp=timestamp)
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="bundle.part_accepted",
            actor_user_id=str(actor["user_id"]),
            device_id=str(capture["device_id"]),
            details={"bundle_id": bundle_id, "role": role, "capture_id": capture_id},
        )
        db.commit()
        updated_bundle = bundle_by_id(db, workspace_id, bundle_id)
        updated_item = bundle_item_by_role(db, workspace_id, bundle_id, role)
        bundle_items = bundle_items_with_captures(db, workspace_id, bundle_id)
    except sqlite3.IntegrityError:
        db.rollback()
        return error_payload(
            409,
            "bundle_part_conflict",
            f"Senses bundle already has a `{role}` part.",
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    bundle_response = bundle_part_response(
        updated_bundle,
        bundle_items,
        updated_item,
        capture,
        chat_provider_app_id=chat_provider_app_id,
    )
    if "dependency_backend_requests" in response:
        bundle_response["dependency_backend_requests"] = response["dependency_backend_requests"]
    bundle_response["capture_response"] = {key: value for key, value in response.items() if key != "dependency_backend_requests"}
    return status_code, bundle_response


def captures_bundle_get(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    speech_provider_app_id = speech_provider_app_id_from_dependencies(dependencies, alias=SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS)
    bundle_id = bounded_identifier(payload.get("bundle_id"), max_length=160)
    if not bundle_id:
        return error_payload(400, "invalid_bundle_id", "captures.bundle_get requires bundle_id.")
    dependency_backend_requests: list[dict[str, object]] = []
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        bundle = bundle_by_id(db, workspace_id, bundle_id)
        if bundle is None:
            return error_payload(404, "bundle_not_found", "No matching Senses capture bundle was found.")
        if not actor_can_access_bundle(db, workspace_id=workspace_id, actor=actor, bundle=bundle):
            return error_payload(403, "senses_permission_forbidden", "You cannot inspect this Senses bundle.")
        items = bundle_items_with_captures(db, workspace_id, bundle_id)
        attempts = bundle_runtime_attempts(db, workspace_id=workspace_id, bundle=bundle, items=items)
    finally:
        db.close()
    audio_capture = bundle_capture_for_role(items, "audio")
    if speech_provider_app_id and audio_capture is not None:
        dependency_backend_requests = claim_transcription_request_for_capture(
            data_root,
            workspace_id=workspace_id,
            capture_id=str(audio_capture["capture_id"]),
            provider_app_id=speech_provider_app_id,
        )
        if dependency_backend_requests:
            ensure_schema(data_root, workspace_id)
            db = connect(data_root)
            try:
                bundle = bundle_by_id(db, workspace_id, bundle_id)
                items = bundle_items_with_captures(db, workspace_id, bundle_id)
                attempts = bundle_runtime_attempts(db, workspace_id=workspace_id, bundle=bundle, items=items) if bundle is not None else []
            finally:
                db.close()
    response = {
        "ok": True,
        "schema_version": BUNDLE_ACCEPTED_SCHEMA_VERSION,
        "bundle_id": bundle_id,
        "bundle": bundle_payload(bundle, items, chat_provider_app_id=chat_provider_app_id),
        "items": bundle_items_payload(items, chat_provider_app_id=chat_provider_app_id),
        "readiness": bundle_readiness_payload(items),
        "runtime_dispatch_attempts": [
            dispatch_attempt_payload(row, chat_provider_app_id=chat_provider_app_id) for row in attempts
        ],
        "chat": chat_link_payload(bundle["thread_id"], provider_app_id=chat_provider_app_id),
        "error": None,
    }
    if dependency_backend_requests:
        response["dependency_backend_requests"] = dependency_backend_requests
    return 200, response


def storage_write_completed(
    data_root: Path,
    workspace_id: str,
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    if text_or_none(payload.get("_app_surface")) != "dependency_backend_request_callback":
        return error_payload(
            403,
            "senses_permission_forbidden",
            "Senses Storage callbacks may only run through the dependency backend callback surface.",
        )
    capture_id = text_or_none(payload.get("capture_id"))
    if not capture_id:
        return error_payload(400, "invalid_capture", "storage_write.completed requires capture_id.")
    if text_or_none(payload.get("dependency_alias")) != STORAGE_WRITE_DEPENDENCY_ALIAS:
        return error_payload(
            400,
            "invalid_dependency_callback",
            "Senses storage callback must come from the storage-file-content-write dependency.",
        )
    expected_request_id = f"write-{capture_id}"
    if text_or_none(payload.get("request_id")) != expected_request_id:
        return error_payload(
            400,
            "invalid_dependency_callback",
            "Senses storage callback request_id did not match the pending Storage write request.",
        )
    request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else None
    if request_payload is None:
        return error_payload(
            400,
            "invalid_dependency_callback",
            "Senses storage callback did not include the original dependency request.",
        )
    original_request_id = text_or_none(request_payload.get("request_id"))
    original_dependency_alias = text_or_none(
        request_payload.get("dependency_alias") or request_payload.get("alias")
    )
    if original_request_id != expected_request_id or original_dependency_alias != STORAGE_WRITE_DEPENDENCY_ALIAS:
        return error_payload(
            400,
            "invalid_dependency_callback",
            "Senses storage callback original request did not match the pending Storage write request.",
        )

    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            db.rollback()
            return error_payload(404, "capture_not_found", "No matching Senses capture was found.")
        if str(capture["status"]) != "storage_pending":
            db.rollback()
            return error_payload(
                409,
                "invalid_capture_state",
                "Senses storage callbacks are accepted only while the capture is storage_pending.",
            )
        if str(payload.get("dependency_backend_status") or "") != "completed":
            updated = mark_capture_storage_failed(
                db,
                workspace_id=workspace_id,
                capture=capture,
                error_code="storage_write_failed",
                error_detail=bounded_text(payload.get("error"), fallback="storage dependency failed", max_length=240),
                timestamp=timestamp,
            )
            update_bundle_items_for_capture(
                db,
                workspace_id=workspace_id,
                capture_id=capture_id,
                timestamp=timestamp,
            )
            db.commit()
            return 200, {
                "ok": True,
                "status": "storage_failed",
                "capture": capture_payload(updated, chat_provider_app_id=chat_provider_app_id),
                "error": None,
            }

        dependency_backend_result = payload.get("dependency_backend_result")
        if not storage_result_provider_app_id(dependency_backend_result):
            db.rollback()
            return error_payload(
                400,
                "invalid_dependency_callback",
                "Senses storage callback result did not include the dependency provider app id.",
            )
        storage_result = storage_result_payload(dependency_backend_result)
        storage_error = validate_storage_result(capture, storage_result)
        if storage_error is not None:
            updated = mark_capture_storage_failed(
                db,
                workspace_id=workspace_id,
                capture=capture,
                error_code="storage_write_failed",
                error_detail=storage_error,
                timestamp=timestamp,
            )
            update_bundle_items_for_capture(
                db,
                workspace_id=workspace_id,
                capture_id=capture_id,
                timestamp=timestamp,
            )
            db.commit()
            return 200, {
                "ok": True,
                "status": "storage_failed",
                "capture": capture_payload(updated, chat_provider_app_id=chat_provider_app_id),
                "error": None,
            }

        db.execute(
            """
            UPDATE captures
            SET status = 'stored',
                storage_file_id = ?,
                workspace_relative_path = ?,
                sha256 = ?,
                size_bytes = ?,
                error_code = NULL,
                updated_at = ?
            WHERE workspace_id = ? AND capture_id = ?
            """,
            (
                storage_result["storage_file_id"],
                storage_result["workspace_relative_path"],
                storage_result["sha256"],
                storage_result["size_bytes"],
                timestamp,
                workspace_id,
                capture_id,
            ),
        )
        db.execute(
            """
            UPDATE ingestion_requests
            SET status = 'stored', error_code = NULL, completed_at = ?
            WHERE workspace_id = ? AND request_id = ?
            """,
            (timestamp, workspace_id, capture["ingestion_request_id"]),
        )
        update_bundle_items_for_capture(
            db,
            workspace_id=workspace_id,
            capture_id=capture_id,
            timestamp=timestamp,
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="capture.stored",
            actor_user_id=None,
            device_id=str(capture["device_id"]),
            details={
                "capture_id": capture_id,
                "storage_file_id": storage_result["storage_file_id"],
                "workspace_relative_path": storage_result["workspace_relative_path"],
                "sha256": storage_result["sha256"],
                "size_bytes": storage_result["size_bytes"],
            },
        )
        db.commit()
        updated = capture_by_id(db, workspace_id, capture_id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 200, {
        "ok": True,
        "status": "stored",
        "capture": capture_payload(updated, chat_provider_app_id=chat_provider_app_id),
        "error": None,
    }


def speech_transcription_completed(
    data_root: Path,
    workspace_id: str,
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    if text_or_none(payload.get("_app_surface")) != "dependency_backend_request_callback":
        return error_payload(
            403,
            "senses_permission_forbidden",
            "Senses speech callbacks may only run through the dependency backend callback surface.",
        )
    capture_id = text_or_none(payload.get("capture_id"))
    if not capture_id:
        return error_payload(400, "invalid_capture", "speech_transcription.completed requires capture_id.")
    if text_or_none(payload.get("dependency_alias")) != SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS:
        return error_payload(
            400,
            "invalid_dependency_callback",
            "Senses speech callback must come from the speech-to-text dependency.",
        )
    expected_request_id = f"transcribe-{capture_id}"
    if text_or_none(payload.get("request_id")) != expected_request_id:
        return error_payload(
            400,
            "invalid_dependency_callback",
            "Senses speech callback request_id did not match the pending transcription request.",
        )

    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            db.rollback()
            return error_payload(404, "capture_not_found", "No matching Senses capture was found.")
        metadata = decode_json_object(capture["metadata_json"])
        current = metadata.get("transcription") if isinstance(metadata.get("transcription"), dict) else {}
        if text_or_none(current.get("request_id")) not in {None, expected_request_id}:
            db.rollback()
            return error_payload(
                400,
                "invalid_dependency_callback",
                "Senses speech callback did not match the capture transcription request.",
            )
        provider_result = payload.get("dependency_backend_result")
        provider_app_id = storage_result_provider_app_id(provider_result) or text_or_none(current.get("provider_app_id"))
        dependency_status = text_or_none(payload.get("dependency_backend_status")) or "failed"
        if dependency_status == "completed":
            result_json = provider_result.get("json") if isinstance(provider_result, dict) and isinstance(provider_result.get("json"), dict) else {}
            text = bounded_text(result_json.get("text"), fallback="", max_length=12000)
            transcript_payload = {
                "status": "completed" if text else "empty",
                "request_id": expected_request_id,
                "provider_app_id": provider_app_id,
                "text": text,
                "language": text_or_none(result_json.get("language")),
                "duration_seconds": optional_float(result_json.get("duration_seconds"), minimum=0.0, maximum=MAX_AUDIO_DURATION_SECONDS),
                "job_id": text_or_none(result_json.get("job_id")),
                "error": None,
                "updated_at": timestamp,
            }
        else:
            transcript_payload = {
                "status": "failed",
                "request_id": expected_request_id,
                "provider_app_id": provider_app_id,
                "text": "",
                "error": bounded_text(payload.get("error"), fallback="speech transcription dependency failed", max_length=500),
                "updated_at": timestamp,
            }
        metadata["transcription"] = transcript_payload
        db.execute(
            """
            UPDATE captures
            SET metadata_json = ?, updated_at = ?
            WHERE workspace_id = ? AND capture_id = ?
            """,
            (encode_json_object(metadata), timestamp, workspace_id, capture_id),
        )
        update_bundle_items_for_capture(
            db,
            workspace_id=workspace_id,
            capture_id=capture_id,
            timestamp=timestamp,
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="capture.transcribed",
            actor_user_id=None,
            device_id=str(capture["device_id"]),
            details={
                "capture_id": capture_id,
                "request_id": expected_request_id,
                "status": transcript_payload["status"],
                "provider_app_id": provider_app_id,
            },
        )
        db.commit()
        updated = capture_by_id(db, workspace_id, capture_id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 200, {
        "ok": True,
        "status": "transcribed",
        "capture": capture_payload(updated, chat_provider_app_id=chat_provider_app_id),
        "transcription": transcription_payload(updated),
        "error": None,
    }


def background_tick(
    data_root: Path,
    workspace_id: str,
    dependencies: dict[str, object],
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    """Claim stored audio captures that need non-blocking Speech transcription."""

    speech_provider_app_id = speech_provider_app_id_from_dependencies(dependencies, alias=SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS)
    if not speech_provider_app_id:
        return 200, {
            "ok": True,
            "status": "idle",
            "transcription_requests": [],
            "error": None,
        }
    claimed = claim_background_transcription_requests(
        data_root,
        workspace_id=workspace_id,
        provider_app_id=speech_provider_app_id,
        limit=BACKGROUND_TRANSCRIPTION_BATCH_SIZE,
    )
    response: dict[str, object] = {
        "ok": True,
        "status": "queued" if claimed else "idle",
        "transcription_requests": [
            {
                "capture_id": item["capture_id"],
                "request_id": item["request_id"],
                "provider_app_id": speech_provider_app_id,
            }
            for item in claimed
        ],
        "error": None,
    }
    if claimed:
        response["dependency_backend_requests"] = [item["request"] for item in claimed]
    return 200, response


def captures_get(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    capture_id = text_or_none(payload.get("capture_id"))
    if not capture_id:
        return error_payload(400, "missing_capture_id", "captures.get requires capture_id.")
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            return error_payload(404, "capture_not_found", "No matching Senses capture was found.")
        if not actor_can_access_capture(db, workspace_id=workspace_id, actor=actor, capture=capture):
            return error_payload(403, "senses_permission_forbidden", "You cannot inspect this Senses capture.")
        attempts = db.execute(
            """
            SELECT * FROM runtime_dispatch_attempts
            WHERE workspace_id = ? AND capture_id = ?
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (workspace_id, capture_id),
        ).fetchall()
    finally:
        db.close()
    return 200, {
        "ok": True,
        "capture": capture_payload(capture, chat_provider_app_id=chat_provider_app_id),
        "runtime_dispatch_attempts": [
            dispatch_attempt_payload(row, chat_provider_app_id=chat_provider_app_id) for row in attempts
        ],
        "chat": chat_link_payload(capture["thread_id"], provider_app_id=chat_provider_app_id),
    }


def routing_dispatch_capture(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    capture_id = text_or_none(payload.get("capture_id"))
    if not capture_id:
        return error_payload(400, "missing_capture_id", "routing.dispatch_capture requires capture_id.")
    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    agent_id = bounded_identifier(payload.get("agent_id") or payload.get("agent_type_id"), max_length=128)
    if not agent_id:
        agent_id = DEFAULT_RUNTIME_AGENT_ID

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            db.rollback()
            return error_payload(404, "capture_not_found", "No matching Senses capture was found.")
        if not actor_can_access_capture(db, workspace_id=workspace_id, actor=actor, capture=capture):
            db.rollback()
            return error_payload(403, "senses_permission_forbidden", "You cannot dispatch this Senses capture.")
        if str(capture["status"]) != "stored":
            db.rollback()
            return error_payload(
                409,
                "invalid_capture_state",
                "routing.dispatch_capture requires a capture whose Storage status is stored.",
                capture_status=capture["status"],
            )
        if capture["runtime_session_id"] and capture["turn_id"]:
            db.commit()
            return 200, dispatch_existing_response(capture, chat_provider_app_id=chat_provider_app_id)

        pending = latest_pending_dispatch_attempt(db, workspace_id=workspace_id, capture_id=capture_id)
        if pending is not None:
            db.rollback()
            return error_payload(
                409,
                "dispatch_in_progress",
                "A runtime dispatch attempt is already pending for this capture.",
                attempt=dispatch_attempt_payload(pending, chat_provider_app_id=chat_provider_app_id),
            )

        device = db.execute(
            "SELECT * FROM devices WHERE workspace_id = ? AND device_id = ?",
            (workspace_id, capture["device_id"]),
        ).fetchone()
        if device is None:
            db.rollback()
            return error_payload(404, "device_not_found", "The capture device no longer exists.")

        settings_row = db.execute("SELECT * FROM settings WHERE workspace_id = ?", (workspace_id,)).fetchone()
        settings = dict(settings_row) if settings_row is not None else {}
        routing_session = ensure_routing_session(
            db,
            workspace_id=workspace_id,
            user_id=actor_user_id,
            device_id=str(capture["device_id"]),
            device_session_id=text_or_none(capture["device_session_id"]),
            timestamp=timestamp,
        )
        route = select_capture_route(
            capture=capture,
            routing_session=routing_session,
            settings=settings,
            payload=payload,
            timestamp=timestamp,
        )
        target_thread_kind = str(route["target_thread_kind"])
        if target_thread_kind in {"new_primary", "new_task"}:
            session_pending = latest_pending_dispatch_attempt_for_routing_session(
                db,
                workspace_id=workspace_id,
                routing_session_id=str(routing_session["routing_session_id"]),
                target_thread_kind=target_thread_kind,
            )
            if session_pending is not None:
                db.rollback()
                return error_payload(
                    409,
                    "dispatch_in_progress",
                    "A runtime dispatch attempt is already pending for this routing session target.",
                    attempt=dispatch_attempt_payload(session_pending, chat_provider_app_id=chat_provider_app_id),
                    routing_session_id=routing_session["routing_session_id"],
                )
        previous_attempts = int(
            db.execute(
                """
                SELECT COUNT(*) FROM runtime_dispatch_attempts
                WHERE workspace_id = ? AND capture_id = ?
                """,
                (workspace_id, capture_id),
            ).fetchone()[0]
        )
        attempt_id = prefixed_id("rda")
        request_id = f"dispatch-{attempt_id}"
        runtime_request = runtime_launch_request_for_capture(
            capture=capture,
            device=device,
            attempt_id=attempt_id,
            request_id=request_id,
            route=route,
            agent_id=agent_id,
        )
        db.execute(
            """
            INSERT INTO runtime_dispatch_attempts(
              workspace_id, attempt_id, capture_id, routing_session_id, request_id,
              route_kind, target_thread_kind, status, runtime_session_id, thread_id, turn_id,
              retry_count, agent_id, runtime_request_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                attempt_id,
                capture_id,
                routing_session["routing_session_id"],
                request_id,
                route["route_kind"],
                route["target_thread_kind"],
                route["runtime_session_id"],
                route["thread_id"],
                previous_attempts,
                agent_id,
                encode_json_object(runtime_request),
                timestamp,
                timestamp,
            ),
        )
        db.execute(
            """
            UPDATE routing_sessions
            SET device_session_id = ?,
                last_capture_id = ?,
                last_routing_kind = ?,
                updated_at = ?
            WHERE workspace_id = ? AND routing_session_id = ?
            """,
            (
                capture["device_session_id"],
                capture_id,
                route["route_kind"],
                timestamp,
                workspace_id,
                routing_session["routing_session_id"],
            ),
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="capture.runtime_dispatch_requested",
            actor_user_id=actor_user_id,
            device_id=str(capture["device_id"]),
            details={
                "capture_id": capture_id,
                "attempt_id": attempt_id,
                "request_id": request_id,
                "route_kind": route["route_kind"],
                "target_thread_kind": route["target_thread_kind"],
                "runtime_session_id": route["runtime_session_id"],
                "thread_id": route["thread_id"],
                "agent_id": agent_id,
            },
        )
        db.commit()
        attempt = db.execute(
            "SELECT * FROM runtime_dispatch_attempts WHERE workspace_id = ? AND attempt_id = ?",
            (workspace_id, attempt_id),
        ).fetchone()
        updated_session = db.execute(
            "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
            (workspace_id, routing_session["routing_session_id"]),
        ).fetchone()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    response = {
        "ok": True,
        "status": "dispatch_pending",
        "capture_id": capture_id,
        "routing": route,
        "routing_session": routing_session_payload(updated_session, chat_provider_app_id=chat_provider_app_id),
        "runtime_dispatch_attempt": dispatch_attempt_payload(attempt, chat_provider_app_id=chat_provider_app_id),
        "runtime_launch_requests": [runtime_request],
        "chat": chat_link_payload(route["thread_id"], provider_app_id=chat_provider_app_id),
        "error": None,
    }
    return 202, response


def routing_dispatch_bundle(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    bundle_id = bounded_identifier(payload.get("bundle_id"), max_length=160)
    if not bundle_id:
        return error_payload(400, "invalid_bundle_id", "routing.dispatch_bundle requires bundle_id.")
    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    agent_id = bounded_identifier(payload.get("agent_id") or payload.get("agent_type_id"), max_length=128)
    if not agent_id:
        agent_id = DEFAULT_RUNTIME_AGENT_ID

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        bundle = bundle_by_id(db, workspace_id, bundle_id)
        if bundle is None:
            db.rollback()
            return error_payload(404, "bundle_not_found", "No matching Senses capture bundle was found.")
        if not actor_can_access_bundle(db, workspace_id=workspace_id, actor=actor, bundle=bundle):
            db.rollback()
            return error_payload(403, "senses_permission_forbidden", "You cannot dispatch this Senses bundle.")
        items = bundle_items_with_captures(db, workspace_id, bundle_id)
        readiness = bundle_readiness_payload(items)
        if not readiness["ready"]:
            db.rollback()
            return error_payload(
                409,
                "invalid_bundle_state",
                "routing.dispatch_bundle requires a stored frame, stored audio, and completed non-empty transcript.",
                bundle_id=bundle_id,
                readiness=readiness,
            )
        frame_capture = bundle_capture_for_role(items, "frame")
        audio_capture = bundle_capture_for_role(items, "audio")
        if frame_capture is None or audio_capture is None:
            db.rollback()
            return error_payload(
                409,
                "invalid_bundle_state",
                "routing.dispatch_bundle requires both frame and audio bundle parts.",
                bundle_id=bundle_id,
                readiness=readiness,
            )
        if bundle["runtime_session_id"] and bundle["turn_id"]:
            db.commit()
            return 200, bundle_dispatch_existing_response(
                bundle,
                items,
                chat_provider_app_id=chat_provider_app_id,
            )

        pending = latest_pending_dispatch_attempt(db, workspace_id=workspace_id, capture_id=str(frame_capture["capture_id"]))
        if pending is not None:
            db.rollback()
            return error_payload(
                409,
                "dispatch_in_progress",
                "A runtime dispatch attempt is already pending for this bundle frame.",
                attempt=dispatch_attempt_payload(pending, chat_provider_app_id=chat_provider_app_id),
                bundle_id=bundle_id,
            )

        device = db.execute(
            "SELECT * FROM devices WHERE workspace_id = ? AND device_id = ?",
            (workspace_id, frame_capture["device_id"]),
        ).fetchone()
        if device is None:
            db.rollback()
            return error_payload(404, "device_not_found", "The bundle device no longer exists.")

        settings_row = db.execute("SELECT * FROM settings WHERE workspace_id = ?", (workspace_id,)).fetchone()
        settings = dict(settings_row) if settings_row is not None else {}
        routing_session = ensure_routing_session(
            db,
            workspace_id=workspace_id,
            user_id=actor_user_id,
            device_id=str(frame_capture["device_id"]),
            device_session_id=text_or_none(frame_capture["device_session_id"]),
            timestamp=timestamp,
        )
        route = select_capture_route(
            capture=frame_capture,
            routing_session=routing_session,
            settings=settings,
            payload=payload,
            timestamp=timestamp,
        )
        target_thread_kind = str(route["target_thread_kind"])
        if target_thread_kind in {"new_primary", "new_task"}:
            session_pending = latest_pending_dispatch_attempt_for_routing_session(
                db,
                workspace_id=workspace_id,
                routing_session_id=str(routing_session["routing_session_id"]),
                target_thread_kind=target_thread_kind,
            )
            if session_pending is not None:
                db.rollback()
                return error_payload(
                    409,
                    "dispatch_in_progress",
                    "A runtime dispatch attempt is already pending for this routing session target.",
                    attempt=dispatch_attempt_payload(session_pending, chat_provider_app_id=chat_provider_app_id),
                    routing_session_id=routing_session["routing_session_id"],
                    bundle_id=bundle_id,
                )

        previous_attempts = int(
            db.execute(
                """
                SELECT COUNT(*) FROM runtime_dispatch_attempts
                WHERE workspace_id = ? AND capture_id = ?
                """,
                (workspace_id, frame_capture["capture_id"]),
            ).fetchone()[0]
        )
        attempt_id = prefixed_id("rda")
        request_id = f"dispatch-bundle-{attempt_id}"
        transcript = str(readiness["transcript"])
        runtime_request = runtime_launch_request_for_bundle(
            bundle=bundle,
            frame_capture=frame_capture,
            audio_capture=audio_capture,
            device=device,
            attempt_id=attempt_id,
            request_id=request_id,
            route=route,
            agent_id=agent_id,
            transcript=transcript,
        )
        db.execute(
            """
            INSERT INTO runtime_dispatch_attempts(
              workspace_id, attempt_id, capture_id, routing_session_id, request_id,
              route_kind, target_thread_kind, status, runtime_session_id, thread_id, turn_id,
              retry_count, agent_id, runtime_request_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                attempt_id,
                frame_capture["capture_id"],
                routing_session["routing_session_id"],
                request_id,
                route["route_kind"],
                route["target_thread_kind"],
                route["runtime_session_id"],
                route["thread_id"],
                previous_attempts,
                agent_id,
                encode_json_object(runtime_request),
                timestamp,
                timestamp,
            ),
        )
        db.execute(
            """
            UPDATE capture_bundles
            SET status = 'dispatching',
                error_code = NULL,
                updated_at = ?
            WHERE workspace_id = ? AND bundle_id = ?
            """,
            (timestamp, workspace_id, bundle_id),
        )
        db.execute(
            """
            UPDATE routing_sessions
            SET device_session_id = ?,
                last_capture_id = ?,
                last_routing_kind = ?,
                updated_at = ?
            WHERE workspace_id = ? AND routing_session_id = ?
            """,
            (
                frame_capture["device_session_id"],
                frame_capture["capture_id"],
                route["route_kind"],
                timestamp,
                workspace_id,
                routing_session["routing_session_id"],
            ),
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="bundle.runtime_dispatch_requested",
            actor_user_id=actor_user_id,
            device_id=str(frame_capture["device_id"]),
            details={
                "bundle_id": bundle_id,
                "frame_capture_id": frame_capture["capture_id"],
                "audio_capture_id": audio_capture["capture_id"],
                "attempt_id": attempt_id,
                "request_id": request_id,
                "route_kind": route["route_kind"],
                "target_thread_kind": route["target_thread_kind"],
                "runtime_session_id": route["runtime_session_id"],
                "thread_id": route["thread_id"],
                "agent_id": agent_id,
            },
        )
        db.commit()
        attempt = db.execute(
            "SELECT * FROM runtime_dispatch_attempts WHERE workspace_id = ? AND attempt_id = ?",
            (workspace_id, attempt_id),
        ).fetchone()
        updated_bundle = bundle_by_id(db, workspace_id, bundle_id)
        updated_items = bundle_items_with_captures(db, workspace_id, bundle_id)
        updated_session = db.execute(
            "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
            (workspace_id, routing_session["routing_session_id"]),
        ).fetchone()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 202, {
        "ok": True,
        "schema_version": BUNDLE_DISPATCH_SCHEMA_VERSION,
        "status": "dispatch_pending",
        "bundle_id": bundle_id,
        "capture_id": frame_capture["capture_id"],
        "bundle": bundle_payload(updated_bundle, updated_items, chat_provider_app_id=chat_provider_app_id),
        "items": bundle_items_payload(updated_items, chat_provider_app_id=chat_provider_app_id),
        "readiness": bundle_readiness_payload(updated_items),
        "routing": route,
        "routing_session": routing_session_payload(updated_session, chat_provider_app_id=chat_provider_app_id),
        "runtime_dispatch_attempt": dispatch_attempt_payload(attempt, chat_provider_app_id=chat_provider_app_id),
        "runtime_launch_requests": [runtime_request],
        "chat": chat_link_payload(route["thread_id"], provider_app_id=chat_provider_app_id),
        "error": None,
    }


def routing_reset(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    routing_session_id = text_or_none(payload.get("routing_session_id"))
    if not routing_session_id:
        return error_payload(400, "missing_routing_session_id", "routing.reset requires routing_session_id.")

    actor_user_id = str(actor["user_id"])
    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """
            SELECT * FROM routing_sessions
            WHERE workspace_id = ? AND routing_session_id = ?
            """,
            (workspace_id, routing_session_id),
        ).fetchone()
        if row is None:
            db.rollback()
            return error_payload(404, "routing_session_not_found", "No matching Senses routing session was found.")
        if str(row["user_id"]) != actor_user_id and not actor_is_manager(actor):
            db.rollback()
            return error_payload(403, "senses_permission_forbidden", "You cannot reset this Senses routing session.")

        db.execute(
            """
            UPDATE routing_sessions
            SET primary_thread_id = NULL,
                primary_runtime_session_id = NULL,
                active_task_thread_id = NULL,
                active_task_runtime_session_id = NULL,
                active_task_capture_id = NULL,
                active_task_started_at = NULL,
                active_task_last_used_at = NULL,
                last_capture_id = NULL,
                last_runtime_session_id = NULL,
                last_thread_id = NULL,
                last_turn_id = NULL,
                last_routing_kind = NULL,
                updated_at = ?
            WHERE workspace_id = ? AND routing_session_id = ?
            """,
            (timestamp, workspace_id, routing_session_id),
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="routing.reset",
            actor_user_id=actor_user_id,
            device_id=text_or_none(row["device_id"]),
            details={"routing_session_id": routing_session_id},
        )
        db.commit()
        updated = db.execute(
            "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
            (workspace_id, routing_session_id),
        ).fetchone()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 200, {
        "ok": True,
        "routing_session": routing_session_payload(updated, chat_provider_app_id=chat_provider_app_id),
        "routing_sessions": list_routing_sessions(
            data_root,
            workspace_id,
            actor,
            include_all=actor_is_manager(actor),
            chat_provider_app_id=chat_provider_app_id,
        ),
    }


def runtime_dispatch_completed(
    data_root: Path,
    workspace_id: str,
    dependencies: dict[str, object],
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    chat_provider_app_id = chat_provider_app_id_from_dependencies(dependencies)
    if text_or_none(payload.get("_app_surface")) != "runtime_request_callback":
        return error_payload(
            403,
            "senses_permission_forbidden",
            "Senses runtime dispatch callbacks may only run through the runtime request callback surface.",
        )
    capture_id = text_or_none(payload.get("capture_id"))
    bundle_id = text_or_none(payload.get("bundle_id"))
    attempt_id = text_or_none(payload.get("attempt_id"))
    request_id = text_or_none(payload.get("request_id"))
    if not capture_id or not attempt_id or not request_id:
        return error_payload(
            400,
            "invalid_runtime_callback",
            "runtime_dispatch.completed requires capture_id, attempt_id, and request_id.",
        )
    status = text_or_none(payload.get("runtime_request_status")) or "failed"
    runtime_session_id = text_or_none(payload.get("runtime_session_id"))
    turn_id = text_or_none(payload.get("turn_id"))
    error_detail = bounded_text(payload.get("error"), fallback="", max_length=500)
    timestamp = now_timestamp()

    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        attempt = db.execute(
            """
            SELECT * FROM runtime_dispatch_attempts
            WHERE workspace_id = ? AND attempt_id = ? AND capture_id = ?
            """,
            (workspace_id, attempt_id, capture_id),
        ).fetchone()
        if attempt is None:
            db.rollback()
            return error_payload(404, "dispatch_attempt_not_found", "No matching Senses runtime dispatch attempt was found.")
        if str(attempt["request_id"]) != request_id:
            db.rollback()
            return error_payload(
                400,
                "invalid_runtime_callback",
                "Senses runtime callback request_id did not match the pending dispatch attempt.",
            )
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            db.rollback()
            return error_payload(404, "capture_not_found", "No matching Senses capture was found.")
        if str(attempt["status"]) != "pending" or attempt["completed_at"]:
            routing_session = None
            routing_session_id = text_or_none(attempt["routing_session_id"])
            if routing_session_id:
                routing_session = db.execute(
                    "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
                    (workspace_id, routing_session_id),
                ).fetchone()
            db.commit()
            return 200, {
                "ok": True,
                "status": attempt["status"],
                "capture": capture_payload(capture, chat_provider_app_id=chat_provider_app_id),
                "runtime_dispatch_attempt": dispatch_attempt_payload(attempt, chat_provider_app_id=chat_provider_app_id),
                "routing_session": routing_session_payload(routing_session, chat_provider_app_id=chat_provider_app_id),
                "chat": chat_link_payload(capture["thread_id"], provider_app_id=chat_provider_app_id),
                "error": None,
            }

        callback_json = {
            "runtime_request_status": status,
            "runtime_session_id": runtime_session_id,
            "turn_id": turn_id,
            "error": error_detail,
        }
        if status != "submitted":
            db.execute(
                """
                UPDATE runtime_dispatch_attempts
                SET status = 'failed',
                    error_code = 'runtime_dispatch_failed',
                    error_detail = ?,
                    callback_json = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE workspace_id = ? AND attempt_id = ?
                """,
                (error_detail or "runtime request failed", encode_json_object(callback_json), timestamp, timestamp, workspace_id, attempt_id),
            )
            db.execute(
                """
                UPDATE captures
                SET error_code = 'runtime_dispatch_failed', updated_at = ?
                WHERE workspace_id = ? AND capture_id = ?
                """,
                (timestamp, workspace_id, capture_id),
            )
            if bundle_id:
                db.execute(
                    """
                    UPDATE capture_bundles
                    SET status = 'failed',
                        error_code = 'runtime_dispatch_failed',
                        updated_at = ?,
                        completed_at = ?
                    WHERE workspace_id = ? AND bundle_id = ?
                    """,
                    (timestamp, timestamp, workspace_id, bundle_id),
                )
            write_audit(
                db,
                workspace_id=workspace_id,
                event_type="capture.runtime_dispatch_failed",
                actor_user_id=None,
                device_id=str(capture["device_id"]),
                details={"capture_id": capture_id, "attempt_id": attempt_id, "error": error_detail},
            )
            db.commit()
            updated_attempt = db.execute(
                "SELECT * FROM runtime_dispatch_attempts WHERE workspace_id = ? AND attempt_id = ?",
                (workspace_id, attempt_id),
            ).fetchone()
            updated_capture = capture_by_id(db, workspace_id, capture_id)
            return 200, {
                "ok": True,
                "status": "failed",
                "capture": capture_payload(updated_capture, chat_provider_app_id=chat_provider_app_id),
                "runtime_dispatch_attempt": dispatch_attempt_payload(
                    updated_attempt,
                    chat_provider_app_id=chat_provider_app_id,
                ),
                "error": None,
            }

        if not runtime_session_id or not turn_id:
            db.rollback()
            return error_payload(
                400,
                "invalid_runtime_callback",
                "A submitted Senses runtime callback requires runtime_session_id and turn_id.",
            )
        thread_id = text_or_none(attempt["thread_id"]) or runtime_session_id
        db.execute(
            """
            UPDATE runtime_dispatch_attempts
            SET status = 'submitted',
                runtime_session_id = ?,
                thread_id = ?,
                turn_id = ?,
                error_code = NULL,
                error_detail = NULL,
                callback_json = ?,
                updated_at = ?,
                completed_at = ?
            WHERE workspace_id = ? AND attempt_id = ?
            """,
            (
                runtime_session_id,
                thread_id,
                turn_id,
                encode_json_object(callback_json),
                timestamp,
                timestamp,
                workspace_id,
                attempt_id,
            ),
        )
        db.execute(
            """
            UPDATE captures
            SET runtime_session_id = ?,
                thread_id = ?,
                turn_id = ?,
                error_code = NULL,
                updated_at = ?
            WHERE workspace_id = ? AND capture_id = ?
            """,
            (runtime_session_id, thread_id, turn_id, timestamp, workspace_id, capture_id),
        )
        if bundle_id:
            db.execute(
                """
                UPDATE capture_bundles
                SET status = 'dispatched',
                    runtime_session_id = ?,
                    thread_id = ?,
                    turn_id = ?,
                    error_code = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE workspace_id = ? AND bundle_id = ?
                """,
                (
                    runtime_session_id,
                    thread_id,
                    turn_id,
                    timestamp,
                    timestamp,
                    workspace_id,
                    bundle_id,
                ),
            )
        update_routing_session_after_runtime_callback(
            db,
            workspace_id=workspace_id,
            attempt=attempt,
            capture=capture,
            runtime_session_id=runtime_session_id,
            thread_id=thread_id,
            turn_id=turn_id,
            timestamp=timestamp,
        )
        write_audit(
            db,
            workspace_id=workspace_id,
            event_type="capture.runtime_dispatched",
            actor_user_id=None,
            device_id=str(capture["device_id"]),
            details={
                "capture_id": capture_id,
                "attempt_id": attempt_id,
                "runtime_session_id": runtime_session_id,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "route_kind": attempt["route_kind"],
            },
        )
        db.commit()
        updated_capture = capture_by_id(db, workspace_id, capture_id)
        updated_attempt = db.execute(
            "SELECT * FROM runtime_dispatch_attempts WHERE workspace_id = ? AND attempt_id = ?",
            (workspace_id, attempt_id),
        ).fetchone()
        routing_session = db.execute(
            "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
            (workspace_id, attempt["routing_session_id"]),
        ).fetchone()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return 200, {
        "ok": True,
        "status": "submitted",
        "capture": capture_payload(updated_capture, chat_provider_app_id=chat_provider_app_id),
        "runtime_dispatch_attempt": dispatch_attempt_payload(
            updated_attempt,
            chat_provider_app_id=chat_provider_app_id,
        ),
        "routing_session": routing_session_payload(routing_session, chat_provider_app_id=chat_provider_app_id),
        "chat": chat_link_payload(
            updated_capture["thread_id"] if updated_capture is not None else None,
            provider_app_id=chat_provider_app_id,
        ),
        "error": None,
    }


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


def list_captures(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    *,
    include_all: bool,
    limit: int = 50,
    chat_provider_app_id: str | None = None,
) -> list[dict[str, object]]:
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        params: list[object] = [workspace_id]
        where = ["workspace_id = ?"]
        if not include_all:
            where.append(
                "device_id IN (SELECT device_id FROM devices WHERE workspace_id = ? AND owner_user_id = ?)"
            )
            params.extend([workspace_id, actor["user_id"]])
        rows = db.execute(
            f"""
            SELECT * FROM captures
            WHERE {" AND ".join(where)}
            ORDER BY captured_at DESC, created_at DESC
            LIMIT ?
            """,
            [*params, max(1, min(250, int(limit)))],
        ).fetchall()
    finally:
        db.close()
    return [capture_payload(row, chat_provider_app_id=chat_provider_app_id) for row in rows]


def list_capture_bundles(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    *,
    include_all: bool,
    limit: int = 50,
    chat_provider_app_id: str | None = None,
) -> list[dict[str, object]]:
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        params: list[object] = [workspace_id]
        where = ["workspace_id = ?"]
        if not include_all:
            where.append("user_id = ?")
            params.append(actor["user_id"])
        rows = db.execute(
            f"""
            SELECT * FROM capture_bundles
            WHERE {" AND ".join(where)}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            [*params, max(1, min(250, int(limit)))],
        ).fetchall()
        bundle_ids = [str(row["bundle_id"]) for row in rows]
        items_by_bundle = {
            bundle_id: bundle_items_with_captures(db, workspace_id, bundle_id)
            for bundle_id in bundle_ids
        }
    finally:
        db.close()
    return [
        bundle_payload(row, items_by_bundle.get(str(row["bundle_id"]), []), chat_provider_app_id=chat_provider_app_id)
        for row in rows
    ]


def list_routing_sessions(
    data_root: Path,
    workspace_id: str,
    actor: dict[str, str | None],
    *,
    include_all: bool,
    limit: int = 50,
    chat_provider_app_id: str | None = None,
) -> list[dict[str, object]]:
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        params: list[object] = [workspace_id]
        where = ["workspace_id = ?"]
        if not include_all:
            where.append("user_id = ?")
            params.append(actor["user_id"])
        rows = db.execute(
            f"""
            SELECT * FROM routing_sessions
            WHERE {" AND ".join(where)}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            [*params, max(1, min(250, int(limit)))],
        ).fetchall()
    finally:
        db.close()
    return [routing_session_payload(row, chat_provider_app_id=chat_provider_app_id) for row in rows]


def actor_can_access_capture(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    actor: dict[str, str | None],
    capture: sqlite3.Row,
) -> bool:
    if actor_is_manager(actor):
        return True
    owner = db.execute(
        """
        SELECT owner_user_id FROM devices
        WHERE workspace_id = ? AND device_id = ?
        """,
        (workspace_id, capture["device_id"]),
    ).fetchone()
    return owner is not None and str(owner["owner_user_id"]) == str(actor.get("user_id") or "")


def actor_can_access_bundle(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    actor: dict[str, str | None],
    bundle: sqlite3.Row,
) -> bool:
    if actor_is_manager(actor):
        return True
    if str(bundle["user_id"]) == str(actor.get("user_id") or ""):
        return True
    owner = db.execute(
        """
        SELECT owner_user_id FROM devices
        WHERE workspace_id = ? AND device_id = ?
        """,
        (workspace_id, bundle["device_id"]),
    ).fetchone()
    return owner is not None and str(owner["owner_user_id"]) == str(actor.get("user_id") or "")


def latest_pending_dispatch_attempt(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    capture_id: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM runtime_dispatch_attempts
        WHERE workspace_id = ?
          AND capture_id = ?
          AND status IN ('pending', 'submitted')
          AND completed_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (workspace_id, capture_id),
    ).fetchone()


def latest_pending_dispatch_attempt_for_routing_session(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    routing_session_id: str,
    target_thread_kind: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM runtime_dispatch_attempts
        WHERE workspace_id = ?
          AND routing_session_id = ?
          AND target_thread_kind = ?
          AND status IN ('pending', 'submitted')
          AND completed_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (workspace_id, routing_session_id, target_thread_kind),
    ).fetchone()


def dispatch_existing_response(capture: sqlite3.Row, *, chat_provider_app_id: str | None = None) -> dict[str, object]:
    return {
        "ok": True,
        "status": "dispatched",
        "capture_id": capture["capture_id"],
        "capture": capture_payload(capture, chat_provider_app_id=chat_provider_app_id),
        "runtime_launch_requests": [],
        "chat": chat_link_payload(capture["thread_id"], provider_app_id=chat_provider_app_id),
        "error": None,
    }


def ensure_routing_session(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    user_id: str,
    device_id: str,
    device_session_id: str | None,
    timestamp: str,
) -> sqlite3.Row:
    row = db.execute(
        """
        SELECT * FROM routing_sessions
        WHERE workspace_id = ? AND user_id = ? AND device_id = ?
        """,
        (workspace_id, user_id, device_id),
    ).fetchone()
    if row is not None:
        if device_session_id and row["device_session_id"] != device_session_id:
            db.execute(
                """
                UPDATE routing_sessions
                SET device_session_id = ?, updated_at = ?
                WHERE workspace_id = ? AND routing_session_id = ?
                """,
                (device_session_id, timestamp, workspace_id, row["routing_session_id"]),
            )
            row = db.execute(
                "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
                (workspace_id, row["routing_session_id"]),
            ).fetchone()
        return row
    routing_session_id = prefixed_id("rts")
    db.execute(
        """
        INSERT INTO routing_sessions(
          workspace_id, routing_session_id, user_id, device_id, device_session_id,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (workspace_id, routing_session_id, user_id, device_id, device_session_id, timestamp, timestamp),
    )
    created = db.execute(
        "SELECT * FROM routing_sessions WHERE workspace_id = ? AND routing_session_id = ?",
        (workspace_id, routing_session_id),
    ).fetchone()
    if created is None:
        raise RuntimeError("Senses failed to create a routing session.")
    return created


def select_capture_route(
    *,
    capture: sqlite3.Row,
    routing_session: sqlite3.Row,
    settings: dict[str, object],
    payload: dict[str, object],
    timestamp: str,
) -> dict[str, object]:
    prompt = str(capture["prompt"] or "")
    metadata = decode_json_object(capture["metadata_json"])
    hint = normalize_routing_hint(
        payload.get("routing_hint")
        or payload.get("route")
        or payload.get("thread_policy")
        or metadata.get("routing_hint")
    )
    followup_window = bounded_int(
        settings.get("routing_followup_window_seconds"),
        default=300,
        minimum=FOLLOWUP_ROUTE_WINDOW_SECONDS_MIN,
        maximum=FOLLOWUP_ROUTE_WINDOW_SECONDS_MAX,
    )
    if hint in {"new", "new_thread", "explicit_new_thread"} or bool(payload.get("force_new_thread")):
        return route_payload(
            route_kind="new_thread",
            target_thread_kind="new",
            reason="explicit_new_thread",
        )
    if hint in {"primary", "main"}:
        return primary_route_payload(routing_session, reason="explicit_primary")
    if hint in {"task", "task_thread", "long_task"}:
        return task_route_payload(routing_session, timestamp=timestamp, followup_window=followup_window, reason="explicit_task")
    if prompt_is_long_task(prompt):
        return task_route_payload(routing_session, timestamp=timestamp, followup_window=followup_window, reason="long_task_prompt")
    if route_is_close_followup(routing_session, timestamp=timestamp, followup_window=followup_window):
        return route_payload(
            route_kind="followup",
            target_thread_kind=thread_role_for_existing_route(routing_session),
            reason="recent_active_thread",
            runtime_session_id=text_or_none(routing_session["last_runtime_session_id"]),
            thread_id=text_or_none(routing_session["last_thread_id"]),
        )
    return primary_route_payload(routing_session, reason="short_question")


def normalize_routing_hint(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def primary_route_payload(routing_session: sqlite3.Row, *, reason: str) -> dict[str, object]:
    runtime_session_id = text_or_none(routing_session["primary_runtime_session_id"])
    thread_id = text_or_none(routing_session["primary_thread_id"])
    return route_payload(
        route_kind="primary",
        target_thread_kind="primary" if runtime_session_id else "new_primary",
        reason=reason,
        runtime_session_id=runtime_session_id,
        thread_id=thread_id,
    )


def task_route_payload(
    routing_session: sqlite3.Row,
    *,
    timestamp: str,
    followup_window: int,
    reason: str,
) -> dict[str, object]:
    runtime_session_id = text_or_none(routing_session["active_task_runtime_session_id"])
    thread_id = text_or_none(routing_session["active_task_thread_id"])
    if runtime_session_id and not active_task_is_recent(routing_session, timestamp=timestamp, followup_window=followup_window):
        runtime_session_id = None
        thread_id = None
    return route_payload(
        route_kind="task",
        target_thread_kind="active_task" if runtime_session_id else "new_task",
        reason=reason,
        runtime_session_id=runtime_session_id,
        thread_id=thread_id,
    )


def route_payload(
    *,
    route_kind: str,
    target_thread_kind: str,
    reason: str,
    runtime_session_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, object]:
    return {
        "route_kind": route_kind,
        "target_thread_kind": target_thread_kind,
        "reason": reason,
        "runtime_session_id": runtime_session_id,
        "thread_id": thread_id,
        "creates_new_thread": not bool(runtime_session_id),
    }


def route_is_close_followup(
    routing_session: sqlite3.Row,
    *,
    timestamp: str,
    followup_window: int,
) -> bool:
    if not routing_session["last_runtime_session_id"] or not routing_session["last_thread_id"]:
        return False
    updated_at = text_or_none(routing_session["updated_at"])
    if not updated_at:
        return False
    return seconds_between(updated_at, timestamp) <= followup_window


def active_task_is_recent(
    routing_session: sqlite3.Row,
    *,
    timestamp: str,
    followup_window: int,
) -> bool:
    last_used_at = text_or_none(routing_session["active_task_last_used_at"])
    if not last_used_at:
        return False
    return seconds_between(last_used_at, timestamp) <= followup_window


def seconds_between(start: str, end: str) -> int:
    started = parse_iso_datetime(start)
    ended = parse_iso_datetime(end)
    if started is None or ended is None:
        return 10**9
    return max(0, int((ended - started).total_seconds()))


def parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def thread_role_for_existing_route(routing_session: sqlite3.Row) -> str:
    if routing_session["last_thread_id"] and routing_session["last_thread_id"] == routing_session["primary_thread_id"]:
        return "primary"
    if routing_session["last_thread_id"] and routing_session["last_thread_id"] == routing_session["active_task_thread_id"]:
        return "active_task"
    return "existing"


def prompt_is_long_task(prompt: str) -> bool:
    normalized = prompt.strip().lower()
    if len(normalized) >= LONG_TASK_PROMPT_LENGTH:
        return True
    return any(keyword in normalized for keyword in LONG_TASK_KEYWORDS)


def runtime_launch_request_for_capture(
    *,
    capture: sqlite3.Row,
    device: sqlite3.Row,
    attempt_id: str,
    request_id: str,
    route: dict[str, object],
    agent_id: str,
) -> dict[str, object]:
    request: dict[str, object] = {
        "request_id": request_id,
        "client_message_id": f"senses:{capture['capture_id']}:{attempt_id}",
        "input_text": runtime_input_text(capture=capture, device=device, route=route),
        "attachments": [runtime_attachment_for_capture(capture)],
        "app_references": [
            {
                "app_id": APP_ID,
                "entity_type": "capture",
                "entity_id": capture["capture_id"],
                "label": "Senses capture",
            }
        ],
        "callback": {
            "action": RUNTIME_DISPATCH_CALLBACK_ACTION,
            "payload": {
                "capture_id": capture["capture_id"],
                "attempt_id": attempt_id,
            },
        },
    }
    runtime_session_id = text_or_none(route.get("runtime_session_id"))
    if runtime_session_id:
        request["runtime_session_id"] = runtime_session_id
    else:
        request.update(
            {
                "agent_id": agent_id,
                "agent_type_id": agent_id,
                "agent_label": "Senses",
                "title": runtime_thread_title(capture=capture, device=device, route=route),
                "requested_mode": "sandbox",
            }
        )
    return request


def runtime_launch_request_for_bundle(
    *,
    bundle: sqlite3.Row,
    frame_capture: sqlite3.Row,
    audio_capture: sqlite3.Row,
    device: sqlite3.Row,
    attempt_id: str,
    request_id: str,
    route: dict[str, object],
    agent_id: str,
    transcript: str,
) -> dict[str, object]:
    request: dict[str, object] = {
        "request_id": request_id,
        "client_message_id": f"senses:{bundle['bundle_id']}:{attempt_id}",
        "input_text": runtime_input_text_for_bundle(
            bundle=bundle,
            frame_capture=frame_capture,
            audio_capture=audio_capture,
            device=device,
            route=route,
            transcript=transcript,
        ),
        "attachments": [
            runtime_attachment_for_capture(frame_capture),
            runtime_attachment_for_capture(audio_capture),
        ],
        "app_references": [
            {
                "app_id": APP_ID,
                "entity_type": "capture_bundle",
                "entity_id": bundle["bundle_id"],
                "label": "Senses multimodal bundle",
            },
            {
                "app_id": APP_ID,
                "entity_type": "capture",
                "entity_id": frame_capture["capture_id"],
                "label": "Senses frame",
            },
            {
                "app_id": APP_ID,
                "entity_type": "capture",
                "entity_id": audio_capture["capture_id"],
                "label": "Senses audio",
            },
        ],
        "callback": {
            "action": RUNTIME_DISPATCH_CALLBACK_ACTION,
            "payload": {
                "capture_id": frame_capture["capture_id"],
                "attempt_id": attempt_id,
                "bundle_id": bundle["bundle_id"],
            },
        },
    }
    runtime_session_id = text_or_none(route.get("runtime_session_id"))
    if runtime_session_id:
        request["runtime_session_id"] = runtime_session_id
    else:
        request.update(
            {
                "agent_id": agent_id,
                "agent_type_id": agent_id,
                "agent_label": "Senses",
                "title": runtime_thread_title_for_bundle(
                    bundle=bundle,
                    frame_capture=frame_capture,
                    device=device,
                    route=route,
                ),
                "requested_mode": "sandbox",
            }
        )
    return request


def runtime_input_text(
    *,
    capture: sqlite3.Row,
    device: sqlite3.Row,
    route: dict[str, object],
) -> str:
    input_mode = text_or_none(capture["input_mode"]) or ""
    is_audio = input_mode.startswith("audio.")
    prompt = text_or_none(capture["prompt"]) or (
        "Rispondi alla richiesta vocale in modo utile."
        if is_audio
        else "Analizza questo frame e rispondi in modo utile."
    )
    origin_label = capture_origin_label(capture=capture, device=device)
    details = [
        f"Senses capture: {capture['capture_id']}",
        f"Device: {device['display_name']} ({device['device_kind']}/{device['platform']})",
        f"Origin: {origin_label}",
        f"Input: {capture['input_mode']}",
        f"Routing: {route['route_kind']} ({route['reason']})",
    ]
    if is_audio:
        transcription = transcription_payload(capture)
        transcript = text_or_none(transcription.get("text"))
        if transcript:
            details.append(f"Transcript: {transcript}")
        else:
            details.append(
                "Transcript: unavailable; the original audio is attached if the runtime provider can inspect audio files."
            )
    if capture["width"] and capture["height"]:
        details.append(f"Frame: {capture['width']}x{capture['height']}")
    return f"{prompt}\n\n" + "\n".join(details)


def runtime_input_text_for_bundle(
    *,
    bundle: sqlite3.Row,
    frame_capture: sqlite3.Row,
    audio_capture: sqlite3.Row,
    device: sqlite3.Row,
    route: dict[str, object],
    transcript: str,
) -> str:
    origin_label = capture_origin_label(capture=frame_capture, device=device)
    details = [
        f"Senses bundle: {bundle['bundle_id']}",
        f"Frame capture: {frame_capture['capture_id']}",
        f"Audio capture: {audio_capture['capture_id']}",
        f"Device: {device['display_name']} ({device['device_kind']}/{device['platform']})",
        f"Origin: {origin_label}",
        f"Routing: {route['route_kind']} ({route['reason']})",
    ]
    if frame_capture["width"] and frame_capture["height"]:
        details.append(f"Frame: {frame_capture['width']}x{frame_capture['height']}")
    return (
        "Richiesta vocale trascritta:\n"
        f"{transcript}\n\n"
        "Usa l'immagine allegata come contesto visivo e rispondi alla richiesta dell'utente.\n"
        "Non descrivere genericamente l'immagine se non serve.\n\n"
        + "\n".join(details)
    )


def runtime_thread_title(
    *,
    capture: sqlite3.Row,
    device: sqlite3.Row,
    route: dict[str, object],
) -> str:
    device_label = capture_origin_label(capture=capture, device=device)
    is_audio = str(capture["input_mode"] or "").startswith("audio.")
    modality = "vocale" if is_audio else "visiva"
    if route["route_kind"] == "task":
        suffix = f"task {modality}"
    elif route["route_kind"] == "new_thread":
        suffix = f"nuova domanda {modality}"
    else:
        suffix = f"domanda {modality}"
    return f"{device_label} - {suffix}"


def runtime_thread_title_for_bundle(
    *,
    bundle: sqlite3.Row,
    frame_capture: sqlite3.Row,
    device: sqlite3.Row,
    route: dict[str, object],
) -> str:
    device_label = capture_origin_label(capture=frame_capture, device=device)
    if route["route_kind"] == "task":
        suffix = "task multimodale"
    elif route["route_kind"] == "new_thread":
        suffix = "nuova domanda multimodale"
    else:
        suffix = "domanda multimodale"
    custom_title = bounded_text(bundle["prompt"], fallback="", max_length=80)
    return custom_title or f"{device_label} - {suffix}"


def capture_origin_label(
    *,
    capture: sqlite3.Row,
    device: sqlite3.Row | None = None,
) -> str:
    metadata = decode_json_object(capture["metadata_json"])
    for key in ("origin_label", "source_label", "sensor_label", "adapter_label"):
        label = text_or_none(metadata.get(key))
        if label:
            return bounded_text(label, fallback="Senses", max_length=48)
    if capture_origin_kind(capture=capture, device=device) == "meta_glasses":
        return "Occhiali"
    if device is not None:
        return bounded_text(device["display_name"], fallback="Senses", max_length=48)
    return "Senses"


def capture_origin_kind(
    *,
    capture: sqlite3.Row,
    device: sqlite3.Row | None = None,
) -> str:
    metadata = decode_json_object(capture["metadata_json"])
    values = [
        metadata.get("origin_kind"),
        metadata.get("source_kind"),
        metadata.get("adapter_id"),
        metadata.get("adapter"),
        metadata.get("sensor"),
        capture["input_mode"],
    ]
    if device is not None:
        values.extend([device["device_kind"], device["platform"], device["display_name"]])
    normalized = " ".join(str(value or "").lower().replace("-", "_") for value in values)
    if "meta_glasses" in normalized or ("meta" in normalized and ("glass" in normalized or "occhiali" in normalized)):
        return "meta_glasses"
    if "vision" in normalized:
        return "vision"
    if "audio" in normalized:
        return "audio"
    return "device"


def runtime_attachment_for_capture(capture: sqlite3.Row) -> dict[str, object]:
    path = text_or_none(capture["workspace_relative_path"])
    if not path:
        raise RuntimeError("Cannot dispatch a Senses capture without a Storage path.")
    return {
        "id": text_or_none(capture["storage_file_id"]) or capture["capture_id"],
        "workspace_relative_path": path,
        "name": Path(path).name,
        "content_type": capture["content_type"],
        "size_bytes": int(capture["size_bytes"] or 0),
    }


def update_routing_session_after_runtime_callback(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    attempt: sqlite3.Row,
    capture: sqlite3.Row,
    runtime_session_id: str,
    thread_id: str,
    turn_id: str,
    timestamp: str,
) -> None:
    routing_session_id = text_or_none(attempt["routing_session_id"])
    if not routing_session_id:
        return
    updates = [
        "last_capture_id = ?",
        "last_runtime_session_id = ?",
        "last_thread_id = ?",
        "last_turn_id = ?",
        "last_routing_kind = ?",
        "updated_at = ?",
    ]
    values: list[object] = [
        capture["capture_id"],
        runtime_session_id,
        thread_id,
        turn_id,
        attempt["route_kind"],
        timestamp,
    ]
    target_kind = str(attempt["target_thread_kind"] or "")
    if target_kind in {"primary", "new_primary"}:
        updates.extend(["primary_thread_id = ?", "primary_runtime_session_id = ?"])
        values.extend([thread_id, runtime_session_id])
    if target_kind in {"active_task", "new_task"} or str(attempt["route_kind"]) == "task":
        updates.extend(
            [
                "active_task_thread_id = ?",
                "active_task_runtime_session_id = ?",
                "active_task_capture_id = ?",
                "active_task_started_at = COALESCE(active_task_started_at, ?)",
                "active_task_last_used_at = ?",
            ]
        )
        values.extend([thread_id, runtime_session_id, capture["capture_id"], timestamp, timestamp])
    values.extend([workspace_id, routing_session_id])
    db.execute(
        f"""
        UPDATE routing_sessions
        SET {", ".join(updates)}
        WHERE workspace_id = ? AND routing_session_id = ?
        """,
        values,
    )


def prepare_capture_payload(
    payload: dict[str, object],
    settings: dict[str, object],
) -> tuple[dict[str, object], tuple[int, dict[str, object]] | None]:
    action = normalize_action(payload.get("action"))
    is_audio = action == "ingest.audio"
    operation = "ingest.audio" if is_audio else "ingest.frame"
    expected_schema_version = AUDIO_CAPTURE_REQUEST_SCHEMA_VERSION if is_audio else CAPTURE_REQUEST_SCHEMA_VERSION
    supported_content_types = SUPPORTED_AUDIO_CONTENT_TYPES if is_audio else SUPPORTED_FRAME_CONTENT_TYPES
    if text_or_none(payload.get("capture_id")):
        return {}, error_payload(
            400,
            "invalid_capture_id",
            "capture_id is generated by Senses and must not be supplied by the client.",
        )
    schema_version = text_or_none(payload.get("schema_version"))
    if schema_version != expected_schema_version:
        return {}, error_payload(
            400,
            "invalid_schema_version",
            f"{operation} requires schema_version `{expected_schema_version}`.",
        )
    request_id = bounded_identifier(payload.get("request_id"), max_length=128)
    if not request_id:
        return {}, error_payload(400, "invalid_request_id", f"{operation} requires request_id.")
    idempotency_key = bounded_identifier(payload.get("idempotency_key"), max_length=160)
    if not idempotency_key:
        return {}, error_payload(400, "invalid_idempotency_key", f"{operation} requires idempotency_key.")
    device_id = bounded_identifier(payload.get("device_id"), max_length=128)
    device_session_id = bounded_identifier(payload.get("device_session_id"), max_length=128)
    if not device_id or not device_session_id:
        return {}, error_payload(400, "invalid_device", f"{operation} requires device_id and device_session_id.")

    content_type = normalize_content_type(payload.get("content_type"))
    if content_type not in supported_content_types:
        return {}, error_payload(
            415,
            "unsupported_media_type",
            "Senses audio ingestion supports audio/aac, audio/m4a, audio/mp3, audio/mp4, audio/mpeg, audio/ogg, audio/wav, and audio/webm payloads."
            if is_audio
            else "Senses frame ingestion supports image/jpeg and diagnostic image/png payloads.",
        )
    raw_content_base64 = payload.get("content_base64")
    if not isinstance(raw_content_base64, str) or not raw_content_base64.strip():
        return {}, error_payload(400, "invalid_base64", f"{operation} requires content_base64.")
    try:
        decoded = b64decode(raw_content_base64, validate=True)
    except (ValueError, binascii.Error):
        return {}, error_payload(400, "invalid_base64", "content_base64 must be valid base64.")
    max_bytes = bounded_int(
        settings.get("max_audio_bytes" if is_audio else "max_frame_bytes"),
        default=10485760 if is_audio else 8388608,
        minimum=1,
        maximum=52428800,
    )
    if len(decoded) > max_bytes:
        return {}, error_payload(
            413,
            "capture_too_large",
            "Decoded audio bytes exceed the configured Senses max_audio_bytes limit."
            if is_audio
            else "Decoded frame bytes exceed the configured Senses max_frame_bytes limit.",
            **({"max_audio_bytes": max_bytes} if is_audio else {"max_frame_bytes": max_bytes}),
        )
    hash_error = validate_client_content_hash(payload, decoded)
    if hash_error is not None:
        return {}, hash_error
    sanitized, media_error = sanitized_audio_bytes(decoded, content_type) if is_audio else sanitized_frame_bytes(decoded, content_type)
    if media_error is not None:
        return {}, media_error
    if len(sanitized) > max_bytes:
        return {}, error_payload(
            413,
            "capture_too_large",
            "Sanitized audio bytes exceed the configured Senses max_audio_bytes limit."
            if is_audio
            else "Sanitized frame bytes exceed the configured Senses max_frame_bytes limit.",
            **({"max_audio_bytes": max_bytes} if is_audio else {"max_frame_bytes": max_bytes}),
        )

    captured_at, timestamp_error = parse_capture_timestamp(payload.get("captured_at"))
    if timestamp_error is not None:
        return {}, timestamp_error

    metadata = metadata_payload(payload.get("metadata"))
    width = optional_bounded_int(metadata.get("width"), minimum=1, maximum=100000)
    height = optional_bounded_int(metadata.get("height"), minimum=1, maximum=100000)
    duration_seconds = normalized_audio_duration_seconds(payload, metadata) if is_audio else None
    if isinstance(duration_seconds, tuple):
        return {}, duration_seconds
    if duration_seconds is not None:
        metadata["duration_seconds"] = duration_seconds
    prompt = bounded_text(payload.get("prompt"), fallback="", max_length=2048)
    input_mode = bounded_text(payload.get("input_mode"), fallback="audio.push_to_talk" if is_audio else "vision.snapshot", max_length=80)
    client_capture_id = bounded_identifier(payload.get("client_capture_id"), max_length=160)
    sha256 = hashlib.sha256(sanitized).hexdigest()
    request_hash = capture_request_hash(
        {
            "schema_version": schema_version,
            "device_id": device_id,
            "device_session_id": device_session_id,
            "idempotency_key": idempotency_key,
            "client_capture_id": client_capture_id,
            "input_mode": input_mode,
            "prompt": prompt,
            "content_type": content_type,
            "sha256": sha256,
            "size_bytes": len(sanitized),
            "captured_at": captured_at.isoformat(),
            "metadata": metadata,
        }
    )
    return {
        "schema_version": schema_version,
        "request_id": request_id,
        "device_id": device_id,
        "device_session_id": device_session_id,
        "idempotency_key": idempotency_key,
        "client_capture_id": client_capture_id,
        "input_mode": input_mode,
        "prompt": prompt,
        "content_type": content_type,
        "content_base64": b64encode(sanitized).decode("ascii"),
        "captured_at": captured_at.isoformat(),
        "captured_at_datetime": captured_at,
        "metadata": metadata,
        "width": width,
        "height": height,
        "sha256": sha256,
        "size_bytes": len(sanitized),
        "request_hash": request_hash,
    }, None


def normalize_bundle_item_role(value: object) -> str | None:
    role = str(value or "").strip().lower().replace("-", "_")
    if role in BUNDLE_ITEM_ROLES:
        return role
    return None


def bundle_part_capture_payload(
    payload: dict[str, object],
    *,
    role: str,
    bundle_id: str,
) -> dict[str, object]:
    result = dict(payload)
    result["action"] = "ingest.audio" if role == "audio" else "ingest.frame"
    result.setdefault(
        "schema_version",
        AUDIO_CAPTURE_REQUEST_SCHEMA_VERSION if role == "audio" else CAPTURE_REQUEST_SCHEMA_VERSION,
    )
    metadata = metadata_payload(result.get("metadata"))
    metadata["bundle_id"] = bundle_id
    metadata["bundle_role"] = role
    metadata.setdefault("origin_kind", "meta_glasses")
    result["metadata"] = metadata
    if role == "frame":
        result["input_mode"] = bounded_text(result.get("input_mode"), fallback="vision.snapshot", max_length=80)
    else:
        result["input_mode"] = bounded_text(result.get("input_mode"), fallback="audio.push_to_talk", max_length=80)
    return result


def validate_device_for_ingest(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    actor_user_id: str,
    device_id: str,
    device_session_id: str,
) -> tuple[int, dict[str, object]] | None:
    device = db.execute(
        "SELECT * FROM devices WHERE workspace_id = ? AND device_id = ?",
        (workspace_id, device_id),
    ).fetchone()
    if device is None:
        return error_payload(404, "device_not_found", "No matching Senses device was found.")
    if str(device["status"]) != "active" or str(device["owner_user_id"]) != actor_user_id:
        return error_payload(403, "device_not_authorized", "This Maverick user session cannot ingest for that device.")
    device_session = db.execute(
        """
        SELECT * FROM device_sessions
        WHERE workspace_id = ? AND device_session_id = ? AND device_id = ?
        """,
        (workspace_id, device_session_id, device_id),
    ).fetchone()
    if device_session is None:
        return error_payload(400, "invalid_device", "The Senses device_session_id does not match that device.")
    if str(device_session["status"]) != "active" or str(device_session["user_id"]) != actor_user_id:
        return error_payload(403, "device_not_authorized", "The Senses device session is not active for this user.")
    return None


def rate_limit_error(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    device_id: str,
) -> tuple[int, dict[str, object]] | None:
    cutoff = (datetime.now(tz=UTC) - timedelta(seconds=FRAME_RATE_LIMIT_WINDOW_SECONDS)).isoformat()
    count = int(
        db.execute(
            """
            SELECT COUNT(*) FROM ingestion_requests
            WHERE workspace_id = ?
              AND device_id = ?
              AND created_at >= ?
            """,
            (workspace_id, device_id, cutoff),
        ).fetchone()[0]
    )
    if count < FRAME_RATE_LIMIT_MAX:
        return None
    return error_payload(
        429,
        "rate_limited",
        "Senses frame ingestion rate limit exceeded for this device.",
        retry_after_seconds=FRAME_RATE_LIMIT_WINDOW_SECONDS,
    )


def capture_by_id(db: sqlite3.Connection, workspace_id: str, capture_id: str) -> sqlite3.Row | None:
    if not capture_id:
        return None
    return db.execute(
        "SELECT * FROM captures WHERE workspace_id = ? AND capture_id = ?",
        (workspace_id, capture_id),
    ).fetchone()


def capture_by_id_from_root(data_root: Path, workspace_id: str, capture_id: str) -> sqlite3.Row | None:
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        return capture_by_id(db, workspace_id, capture_id)
    finally:
        db.close()


def bundle_by_id(db: sqlite3.Connection, workspace_id: str, bundle_id: str) -> sqlite3.Row | None:
    if not bundle_id:
        return None
    return db.execute(
        "SELECT * FROM capture_bundles WHERE workspace_id = ? AND bundle_id = ?",
        (workspace_id, bundle_id),
    ).fetchone()


def bundle_item_by_role(
    db: sqlite3.Connection,
    workspace_id: str,
    bundle_id: str,
    role: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT * FROM capture_bundle_items
        WHERE workspace_id = ? AND bundle_id = ? AND role = ?
        """,
        (workspace_id, bundle_id, role),
    ).fetchone()


def bundle_items_with_captures(
    db: sqlite3.Connection,
    workspace_id: str,
    bundle_id: str,
) -> list[dict[str, sqlite3.Row | None]]:
    rows = db.execute(
        """
        SELECT * FROM capture_bundle_items
        WHERE workspace_id = ? AND bundle_id = ?
        ORDER BY CASE role WHEN 'frame' THEN 0 WHEN 'audio' THEN 1 ELSE 2 END, created_at
        """,
        (workspace_id, bundle_id),
    ).fetchall()
    return [
        {
            "item": row,
            "capture": capture_by_id(db, workspace_id, str(row["capture_id"])),
        }
        for row in rows
    ]


def bundle_runtime_attempts(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    bundle: sqlite3.Row,
    items: list[dict[str, sqlite3.Row | None]],
) -> list[sqlite3.Row]:
    capture_ids = [
        str(capture["capture_id"])
        for capture in (item.get("capture") for item in items)
        if capture is not None
    ]
    if not capture_ids:
        return []
    placeholders = ", ".join("?" for _ in capture_ids)
    return db.execute(
        f"""
        SELECT * FROM runtime_dispatch_attempts
        WHERE workspace_id = ?
          AND capture_id IN ({placeholders})
        ORDER BY created_at DESC
        LIMIT 25
        """,
        [workspace_id, *capture_ids],
    ).fetchall()


def capture_storage_path(
    *,
    device_id: str,
    capture_id: str,
    captured_at: datetime,
    content_type: str,
) -> str:
    extension = CAPTURE_CONTENT_TYPE_EXTENSIONS[content_type]
    return f"storage/generated/senses/{device_id}/{captured_at.date().isoformat()}/{capture_id}{extension}"


def storage_write_dependency_request(
    capture: sqlite3.Row | None,
    prepared: dict[str, object],
    *,
    reissue: bool = False,
) -> dict[str, object]:
    if capture is None:
        raise RuntimeError("Cannot create Senses Storage dependency request without a capture row.")
    capture_id = str(capture["capture_id"])
    body = {
        "action": "file.content.write",
        "mode": "upsert" if reissue else "create",
        "workspace_relative_path": capture["workspace_relative_path"],
        "content_base64": prepared["content_base64"],
    }
    if reissue:
        body["confirm"] = True
    return {
        "request_id": f"write-{capture_id}",
        "dependency_alias": STORAGE_WRITE_DEPENDENCY_ALIAS,
        "body": body,
        "callback": {
            "action": "storage_write.completed",
            "payload": {"capture_id": capture_id},
        },
    }


def speech_transcription_dependency_request(
    *,
    capture: sqlite3.Row,
    request_id: str,
) -> dict[str, object]:
    capture_id = str(capture["capture_id"])
    request_body: dict[str, object] = {
        "action": "transcribe_file",
        "workspace_relative_path": str(capture["workspace_relative_path"] or ""),
        "content_type": normalize_content_type(capture["content_type"]),
    }
    metadata = decode_json_object(capture["metadata_json"])
    language = text_or_none(metadata.get("language") or metadata.get("language_hint"))
    if language:
        request_body["language"] = language
    return {
        "request_id": request_id,
        "dependency_alias": SPEECH_TRANSCRIPTION_DEPENDENCY_ALIAS,
        "body": request_body,
        "callback": {
            "action": SPEECH_TRANSCRIPTION_CALLBACK_ACTION,
            "payload": {"capture_id": capture_id},
        },
    }


def mark_capture_transcription_requested(
    data_root: Path,
    *,
    workspace_id: str,
    capture_id: str,
    request_id: str,
    provider_app_id: str,
) -> None:
    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None:
            return
        metadata = decode_json_object(capture["metadata_json"])
        metadata["transcription"] = {
            "status": "pending",
            "request_id": request_id,
            "provider_app_id": provider_app_id,
            "text": "",
            "error": None,
            "updated_at": timestamp,
        }
        db.execute(
            """
            UPDATE captures
            SET metadata_json = ?, updated_at = ?
            WHERE workspace_id = ? AND capture_id = ?
            """,
            (encode_json_object(metadata), timestamp, workspace_id, capture_id),
        )
        db.commit()
    finally:
        db.close()


def claim_transcription_request_for_capture(
    data_root: Path,
    *,
    workspace_id: str,
    capture_id: str,
    provider_app_id: str,
) -> list[dict[str, object]]:
    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    try:
        db.execute("BEGIN IMMEDIATE")
        capture = capture_by_id(db, workspace_id, capture_id)
        if capture is None or str(capture["status"]) != "stored" or not str(capture["input_mode"] or "").startswith("audio."):
            db.rollback()
            return []
        metadata = decode_json_object(capture["metadata_json"])
        transcription = metadata.get("transcription") if isinstance(metadata.get("transcription"), dict) else {}
        if not transcription_needs_background_submit(transcription, timestamp=timestamp):
            db.rollback()
            return []
        request_id = text_or_none(transcription.get("request_id")) or f"transcribe-{capture['capture_id']}"
        attempt_count = bounded_int(transcription.get("attempt_count"), default=0, minimum=0, maximum=1000) + 1
        metadata["transcription"] = {
            **transcription,
            "status": "submitted",
            "request_id": request_id,
            "provider_app_id": provider_app_id,
            "text": bounded_text(transcription.get("text"), fallback="", max_length=12000),
            "error": None,
            "attempt_count": attempt_count,
            "submitted_at": timestamp,
            "updated_at": timestamp,
        }
        db.execute(
            """
            UPDATE captures
            SET metadata_json = ?, updated_at = ?
            WHERE workspace_id = ? AND capture_id = ?
            """,
            (encode_json_object(metadata), timestamp, workspace_id, capture["capture_id"]),
        )
        update_bundle_items_for_capture(
            db,
            workspace_id=workspace_id,
            capture_id=capture_id,
            timestamp=timestamp,
        )
        db.commit()
        return [speech_transcription_dependency_request(capture=capture, request_id=request_id)]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def claim_background_transcription_requests(
    data_root: Path,
    *,
    workspace_id: str,
    provider_app_id: str,
    limit: int,
) -> list[dict[str, object]]:
    timestamp = now_timestamp()
    ensure_schema(data_root, workspace_id)
    db = connect(data_root)
    claimed: list[dict[str, object]] = []
    try:
        db.execute("BEGIN IMMEDIATE")
        candidates = db.execute(
            """
            SELECT * FROM captures
            WHERE workspace_id = ?
              AND status = 'stored'
              AND deleted_at IS NULL
              AND input_mode LIKE 'audio.%'
            ORDER BY captured_at ASC
            LIMIT 50
            """,
            (workspace_id,),
        ).fetchall()
        for capture in candidates:
            if len(claimed) >= limit:
                break
            metadata = decode_json_object(capture["metadata_json"])
            transcription = metadata.get("transcription") if isinstance(metadata.get("transcription"), dict) else {}
            if not transcription_needs_background_submit(transcription, timestamp=timestamp):
                continue
            request_id = text_or_none(transcription.get("request_id")) or f"transcribe-{capture['capture_id']}"
            attempt_count = bounded_int(transcription.get("attempt_count"), default=0, minimum=0, maximum=1000) + 1
            metadata["transcription"] = {
                **transcription,
                "status": "submitted",
                "request_id": request_id,
                "provider_app_id": provider_app_id,
                "text": bounded_text(transcription.get("text"), fallback="", max_length=12000),
                "error": None,
                "attempt_count": attempt_count,
                "submitted_at": timestamp,
                "updated_at": timestamp,
            }
            db.execute(
                """
                UPDATE captures
                SET metadata_json = ?, updated_at = ?
                WHERE workspace_id = ? AND capture_id = ?
                """,
                (encode_json_object(metadata), timestamp, workspace_id, capture["capture_id"]),
            )
            update_bundle_items_for_capture(
                db,
                workspace_id=workspace_id,
                capture_id=str(capture["capture_id"]),
                timestamp=timestamp,
            )
            request = speech_transcription_dependency_request(capture=capture, request_id=request_id)
            claimed.append(
                {
                    "capture_id": str(capture["capture_id"]),
                    "request_id": request_id,
                    "request": request,
                }
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return claimed


def transcription_needs_background_submit(transcription: object, *, timestamp: str) -> bool:
    if not isinstance(transcription, dict):
        return False
    status = text_or_none(transcription.get("status")) or ""
    if status == "pending":
        return True
    if status != "submitted":
        return False
    submitted_at = text_or_none(transcription.get("submitted_at") or transcription.get("updated_at"))
    if not submitted_at:
        return True
    return seconds_between(submitted_at, timestamp) >= TRANSCRIPTION_SUBMITTED_LEASE_SECONDS


def ingest_acceptance_response(
    ingestion_request: sqlite3.Row | None,
    capture: sqlite3.Row | None,
) -> dict[str, object]:
    if ingestion_request is None or capture is None:
        raise RuntimeError("Cannot build Senses ingest response without persisted rows.")
    storage = storage_payload(capture)
    return {
        "ok": True,
        "schema_version": CAPTURE_ACCEPTED_SCHEMA_VERSION,
        "request_id": ingestion_request["request_id"],
        "status": "stored" if storage["status"] == "stored" else "accepted",
        "capture_id": capture["capture_id"],
        "idempotency_key": ingestion_request["idempotency_key"],
        "storage": storage,
        "dispatch": {
            "required": True,
            "action": "routing.dispatch_capture",
            "ready_status": "stored",
        },
        "transcription": transcription_payload(capture),
        "error": None,
    }


def storage_payload(capture: sqlite3.Row | None) -> dict[str, object]:
    if capture is None:
        return {}
    status = str(capture["status"])
    if status == "stored":
        storage_status = "stored"
    elif status == "storage_failed":
        storage_status = "failed"
    else:
        storage_status = "pending"
    return {
        "status": storage_status,
        "storage_file_id": capture["storage_file_id"],
        "workspace_relative_path": capture["workspace_relative_path"],
        "sha256": capture["sha256"],
        "size_bytes": capture["size_bytes"],
    }


def capture_payload(row: sqlite3.Row | None, *, chat_provider_app_id: str | None = None) -> dict[str, object]:
    if row is None:
        return {}
    chat = chat_link_payload(row["thread_id"], provider_app_id=chat_provider_app_id)
    return {
        "workspace_id": row["workspace_id"],
        "capture_id": row["capture_id"],
        "device_id": row["device_id"],
        "device_session_id": row["device_session_id"],
        "ingestion_request_id": row["ingestion_request_id"],
        "input_mode": row["input_mode"],
        "prompt": row["prompt"],
        "content_type": row["content_type"],
        "storage": storage_payload(row),
        "width": row["width"],
        "height": row["height"],
        "retention_class": row["retention_class"],
        "status": row["status"],
        "error_code": row["error_code"],
        "captured_at": row["captured_at"],
        "ingested_at": row["ingested_at"],
        "runtime_session_id": row["runtime_session_id"],
        "thread_id": row["thread_id"],
        "turn_id": row["turn_id"],
        "chat": chat,
        "origin": capture_origin_payload(row),
        "transcription": transcription_payload(row),
        "deleted_at": row["deleted_at"],
        "metadata": decode_json_object(row["metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def bundle_action_response(
    bundle: sqlite3.Row | None,
    items: list[dict[str, sqlite3.Row | None]],
    *,
    chat_provider_app_id: str | None,
) -> dict[str, object]:
    payload = bundle_payload(bundle, items, chat_provider_app_id=chat_provider_app_id)
    return {
        "ok": True,
        "schema_version": BUNDLE_ACCEPTED_SCHEMA_VERSION,
        "request_id": payload.get("request_id"),
        "bundle_id": payload.get("bundle_id"),
        "status": payload.get("status"),
        "bundle": payload,
        "items": bundle_items_payload(items, chat_provider_app_id=chat_provider_app_id),
        "readiness": bundle_readiness_payload(items),
        "dispatch": {
            "required": True,
            "action": "routing.dispatch_bundle",
            "ready_status": "ready",
        },
        "error": None,
    }


def bundle_part_response(
    bundle: sqlite3.Row | None,
    items: list[dict[str, sqlite3.Row | None]],
    item: sqlite3.Row | None,
    capture: sqlite3.Row | None,
    *,
    chat_provider_app_id: str | None,
) -> dict[str, object]:
    role = item["role"] if item is not None else None
    capture_payload_value = capture_payload(capture, chat_provider_app_id=chat_provider_app_id)
    payload = bundle_action_response(bundle, items, chat_provider_app_id=chat_provider_app_id)
    payload.update(
        {
            "schema_version": BUNDLE_PART_ACCEPTED_SCHEMA_VERSION,
            "role": role,
            "capture_id": capture_payload_value.get("capture_id"),
            "capture": capture_payload_value,
            "status": capture_payload_value.get("status") or payload.get("status"),
            "storage": capture_payload_value.get("storage") or {},
            "transcription": capture_payload_value.get("transcription") or transcription_response_payload(None),
        }
    )
    return payload


def bundle_dispatch_existing_response(
    bundle: sqlite3.Row,
    items: list[dict[str, sqlite3.Row | None]],
    *,
    chat_provider_app_id: str | None,
) -> dict[str, object]:
    frame_capture = bundle_capture_for_role(items, "frame")
    return {
        "ok": True,
        "schema_version": BUNDLE_DISPATCH_SCHEMA_VERSION,
        "status": "dispatched",
        "bundle_id": bundle["bundle_id"],
        "capture_id": frame_capture["capture_id"] if frame_capture is not None else None,
        "bundle": bundle_payload(bundle, items, chat_provider_app_id=chat_provider_app_id),
        "items": bundle_items_payload(items, chat_provider_app_id=chat_provider_app_id),
        "readiness": bundle_readiness_payload(items),
        "runtime_launch_requests": [],
        "chat": chat_link_payload(bundle["thread_id"], provider_app_id=chat_provider_app_id),
        "error": None,
    }


def bundle_payload(
    row: sqlite3.Row | None,
    items: list[dict[str, sqlite3.Row | None]],
    *,
    chat_provider_app_id: str | None = None,
) -> dict[str, object]:
    if row is None:
        return {}
    frame_capture = bundle_capture_for_role(items, "frame")
    audio_capture = bundle_capture_for_role(items, "audio")
    chat = chat_link_payload(row["thread_id"], provider_app_id=chat_provider_app_id)
    return {
        "workspace_id": row["workspace_id"],
        "bundle_id": row["bundle_id"],
        "request_id": row["request_id"],
        "user_id": row["user_id"],
        "device_id": row["device_id"],
        "device_session_id": row["device_session_id"],
        "status": row["status"],
        "prompt": row["prompt"],
        "frame_capture_id": frame_capture["capture_id"] if frame_capture is not None else None,
        "audio_capture_id": audio_capture["capture_id"] if audio_capture is not None else None,
        "runtime_session_id": row["runtime_session_id"],
        "thread_id": row["thread_id"],
        "turn_id": row["turn_id"],
        "chat": chat,
        "readiness": bundle_readiness_payload(items),
        "items": bundle_items_payload(items, chat_provider_app_id=chat_provider_app_id),
        "error_code": row["error_code"],
        "metadata": decode_json_object(row["metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def bundle_items_payload(
    items: list[dict[str, sqlite3.Row | None]],
    *,
    chat_provider_app_id: str | None,
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for item in items:
        row = item.get("item")
        capture = item.get("capture")
        if row is None:
            continue
        payload.append(
            {
                "workspace_id": row["workspace_id"],
                "bundle_id": row["bundle_id"],
                "role": row["role"],
                "capture_id": row["capture_id"],
                "request_id": row["request_id"],
                "status": row["status"],
                "error_code": row["error_code"],
                "capture": capture_payload(capture, chat_provider_app_id=chat_provider_app_id),
                "metadata": decode_json_object(row["metadata_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return payload


def bundle_readiness_payload(items: list[dict[str, sqlite3.Row | None]]) -> dict[str, object]:
    frame_capture = bundle_capture_for_role(items, "frame")
    audio_capture = bundle_capture_for_role(items, "audio")
    missing_roles = [
        role
        for role, capture in (("frame", frame_capture), ("audio", audio_capture))
        if capture is None
    ]
    transcription = transcription_payload(audio_capture)
    transcript = text_or_none(transcription.get("text")) or ""
    frame_status = str(frame_capture["status"]) if frame_capture is not None else None
    audio_status = str(audio_capture["status"]) if audio_capture is not None else None
    transcription_status = text_or_none(transcription.get("status")) or "not_requested"
    frame_ready = frame_status == "stored"
    audio_ready = audio_status == "stored"
    transcript_ready = transcription_status == "completed" and bool(transcript)
    ready = not missing_roles and frame_ready and audio_ready and transcript_ready
    blocking_code = None
    blocking_detail = None
    if missing_roles:
        blocking_code = "missing_" + "_".join(missing_roles)
        blocking_detail = "Bundle is waiting for required media parts."
    elif not frame_ready:
        blocking_code = "frame_not_stored"
        blocking_detail = "Bundle frame is not stored in Storage yet."
    elif not audio_ready:
        blocking_code = "audio_not_stored"
        blocking_detail = "Bundle audio is not stored in Storage yet."
    elif transcription_status == "completed" and not transcript:
        blocking_code = "transcript_empty"
        blocking_detail = "Speech transcription completed with no usable text."
    elif transcription_status in {"failed", "empty", "unavailable", "not_requested"}:
        blocking_code = f"transcription_{transcription_status}"
        blocking_detail = "Speech transcription is not available for this audio capture."
    elif not transcript_ready:
        blocking_code = "transcription_pending"
        blocking_detail = "Speech transcription has not completed yet."
    return {
        "ready": ready,
        "status": "ready" if ready else blocking_code,
        "blocking_code": blocking_code,
        "blocking_detail": blocking_detail,
        "missing_roles": missing_roles,
        "frame_status": frame_status,
        "audio_status": audio_status,
        "transcription_status": transcription_status,
        "transcript": transcript,
    }


def bundle_capture_for_role(
    items: list[dict[str, sqlite3.Row | None]],
    role: str,
) -> sqlite3.Row | None:
    for item in items:
        row = item.get("item")
        if row is not None and str(row["role"]) == role:
            return item.get("capture")
    return None


def update_bundle_items_for_capture(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    capture_id: str,
    timestamp: str,
) -> None:
    items = db.execute(
        """
        SELECT * FROM capture_bundle_items
        WHERE workspace_id = ? AND capture_id = ?
        """,
        (workspace_id, capture_id),
    ).fetchall()
    if not items:
        return
    capture = capture_by_id(db, workspace_id, capture_id)
    for item in items:
        db.execute(
            """
            UPDATE capture_bundle_items
            SET status = ?, error_code = ?, updated_at = ?
            WHERE workspace_id = ? AND bundle_id = ? AND role = ?
            """,
            (
                capture["status"] if capture is not None else "missing",
                capture["error_code"] if capture is not None else "capture_missing",
                timestamp,
                workspace_id,
                item["bundle_id"],
                item["role"],
            ),
        )
        update_bundle_status_from_items(
            db,
            workspace_id=workspace_id,
            bundle_id=str(item["bundle_id"]),
            timestamp=timestamp,
        )


def update_bundle_status_from_items(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    bundle_id: str,
    timestamp: str,
) -> None:
    bundle = bundle_by_id(db, workspace_id, bundle_id)
    if bundle is None:
        return
    current_status = str(bundle["status"] or "")
    if current_status in {"dispatching", "dispatched"}:
        return
    items = bundle_items_with_captures(db, workspace_id, bundle_id)
    readiness = bundle_readiness_payload(items)
    status = bundle_status_from_readiness(readiness)
    error_code = text_or_none(readiness.get("blocking_code")) if status == "failed" else None
    completed_at = timestamp if status in {"ready", "failed"} else None
    db.execute(
        """
        UPDATE capture_bundles
        SET status = ?,
            error_code = ?,
            updated_at = ?,
            completed_at = COALESCE(?, completed_at)
        WHERE workspace_id = ? AND bundle_id = ?
        """,
        (status, error_code, timestamp, completed_at, workspace_id, bundle_id),
    )


def bundle_status_from_readiness(readiness: dict[str, object]) -> str:
    if readiness.get("ready"):
        return "ready"
    blocking_code = text_or_none(readiness.get("blocking_code")) or ""
    if blocking_code.startswith("missing_"):
        return "waiting_for_parts"
    if blocking_code in {"frame_not_stored", "audio_not_stored"}:
        return "storing"
    if blocking_code == "transcription_pending":
        return "transcribing"
    if blocking_code.startswith("transcription_") or blocking_code == "transcript_empty":
        return "failed"
    return "waiting_for_parts"


def transcription_payload(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return transcription_response_payload(None)
    metadata = decode_json_object(row["metadata_json"])
    transcription = metadata.get("transcription") if isinstance(metadata.get("transcription"), dict) else None
    return transcription_response_payload(transcription)


def transcription_response_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {
            "status": "not_requested",
            "request_id": None,
            "provider_app_id": None,
            "text": "",
            "language": None,
            "duration_seconds": None,
            "job_id": None,
            "error": None,
        }
    return {
        "status": text_or_none(value.get("status")) or "not_requested",
        "request_id": text_or_none(value.get("request_id")),
        "provider_app_id": text_or_none(value.get("provider_app_id")),
        "text": bounded_text(value.get("text"), fallback="", max_length=12000),
        "language": text_or_none(value.get("language")),
        "duration_seconds": optional_float(value.get("duration_seconds"), minimum=0.0, maximum=MAX_AUDIO_DURATION_SECONDS),
        "job_id": text_or_none(value.get("job_id")),
        "error": text_or_none(value.get("error")),
    }


def routing_session_payload(row: sqlite3.Row | None, *, chat_provider_app_id: str | None = None) -> dict[str, object]:
    if row is None:
        return {}
    return {
        "workspace_id": row["workspace_id"],
        "routing_session_id": row["routing_session_id"],
        "user_id": row["user_id"],
        "device_id": row["device_id"],
        "device_session_id": row["device_session_id"],
        "primary_thread_id": row["primary_thread_id"],
        "primary_runtime_session_id": row["primary_runtime_session_id"],
        "active_task_thread_id": row["active_task_thread_id"],
        "active_task_runtime_session_id": row["active_task_runtime_session_id"],
        "active_task_capture_id": row["active_task_capture_id"],
        "active_task_started_at": row["active_task_started_at"],
        "active_task_last_used_at": row["active_task_last_used_at"],
        "last_capture_id": row["last_capture_id"],
        "last_runtime_session_id": row["last_runtime_session_id"],
        "last_thread_id": row["last_thread_id"],
        "last_turn_id": row["last_turn_id"],
        "last_routing_kind": row["last_routing_kind"],
        "primary_chat": chat_link_payload(row["primary_thread_id"], provider_app_id=chat_provider_app_id),
        "active_task_chat": chat_link_payload(row["active_task_thread_id"], provider_app_id=chat_provider_app_id),
        "last_chat": chat_link_payload(row["last_thread_id"], provider_app_id=chat_provider_app_id),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def dispatch_attempt_payload(row: sqlite3.Row | None, *, chat_provider_app_id: str | None = None) -> dict[str, object]:
    if row is None:
        return {}
    return {
        "workspace_id": row["workspace_id"],
        "attempt_id": row["attempt_id"],
        "capture_id": row["capture_id"],
        "routing_session_id": row["routing_session_id"],
        "request_id": row["request_id"],
        "route_kind": row["route_kind"],
        "target_thread_kind": row["target_thread_kind"],
        "status": row["status"],
        "runtime_session_id": row["runtime_session_id"],
        "thread_id": row["thread_id"],
        "turn_id": row["turn_id"],
        "retry_count": row["retry_count"],
        "agent_id": row["agent_id"],
        "error_code": row["error_code"],
        "error_detail": row["error_detail"],
        "chat": chat_link_payload(row["thread_id"], provider_app_id=chat_provider_app_id),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def chat_link_payload(thread_id: object, *, provider_app_id: str | None = None) -> dict[str, object]:
    normalized = text_or_none(thread_id)
    provider = text_or_none(provider_app_id)
    if not normalized:
        return {
            "available": False,
            "thread_id": None,
            "deep_link": None,
            "app_id": provider,
            "app_page": None,
            "status": "pending",
            "label": "Chat pending",
        }
    if not provider:
        return {
            "available": False,
            "thread_id": normalized,
            "deep_link": None,
            "app_id": None,
            "app_page": None,
            "status": "unavailable",
            "label": "Chat unavailable",
        }
    app_page = f"threads/{normalized}"
    return {
        "available": True,
        "thread_id": normalized,
        "deep_link": f"/app/{provider}/{app_page}",
        "app_id": provider,
        "app_page": app_page,
        "status": "linked",
        "label": "Chat linked",
    }


def capture_origin_payload(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    metadata = decode_json_object(row["metadata_json"])
    return {
        "label": capture_origin_label(capture=row),
        "kind": capture_origin_kind(capture=row),
        "adapter_id": text_or_none(metadata.get("adapter_id") or metadata.get("adapter")),
        "input_modes": [row["input_mode"]] if text_or_none(row["input_mode"]) else [],
    }


def storage_result_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result_json = value.get("json") if isinstance(value.get("json"), dict) else value
    if not isinstance(result_json, dict):
        return {}
    file_payload = result_json.get("file") if isinstance(result_json.get("file"), dict) else {}
    audit = result_json.get("audit") if isinstance(result_json.get("audit"), dict) else {}
    storage_file_id = text_or_none(
        file_payload.get("file_id")
        or file_payload.get("stable_storage_file_id")
        or file_payload.get("id")
        or result_json.get("file_id")
    )
    workspace_relative_path = text_or_none(file_payload.get("workspace_relative_path") or result_json.get("workspace_relative_path"))
    sha256 = text_or_none(file_payload.get("sha256") or audit.get("sha256") or result_json.get("sha256"))
    size_bytes = optional_bounded_int(file_payload.get("size_bytes") or result_json.get("bytes_written"), minimum=0, maximum=52428800)
    return {
        "storage_file_id": storage_file_id,
        "workspace_relative_path": workspace_relative_path,
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def storage_result_provider_app_id(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    provider_app_id = text_or_none(
        value.get("dependency_provider_app_id") or value.get("provider_app_id")
    )
    if provider_app_id:
        return provider_app_id
    result_json = value.get("json") if isinstance(value.get("json"), dict) else {}
    if not isinstance(result_json, dict):
        return ""
    return text_or_none(
        result_json.get("dependency_provider_app_id") or result_json.get("provider_app_id")
    )


def validate_storage_result(capture: sqlite3.Row, storage_result: dict[str, object]) -> str | None:
    if not storage_result.get("storage_file_id"):
        return "Storage result did not include a file id."
    if storage_result.get("workspace_relative_path") != capture["workspace_relative_path"]:
        return "Storage result path did not match the Senses capture path."
    if storage_result.get("sha256") != capture["sha256"]:
        return "Storage result sha256 did not match the Senses capture hash."
    if storage_result.get("size_bytes") != capture["size_bytes"]:
        return "Storage result size did not match the Senses capture size."
    return None


def mark_capture_storage_failed(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    capture: sqlite3.Row,
    error_code: str,
    error_detail: str,
    timestamp: str,
) -> sqlite3.Row | None:
    db.execute(
        """
        UPDATE captures
        SET status = 'storage_failed', error_code = ?, updated_at = ?
        WHERE workspace_id = ? AND capture_id = ?
        """,
        (error_code, timestamp, workspace_id, capture["capture_id"]),
    )
    db.execute(
        """
        UPDATE ingestion_requests
        SET status = 'storage_failed', error_code = ?, completed_at = ?
        WHERE workspace_id = ? AND request_id = ?
        """,
        (error_code, timestamp, workspace_id, capture["ingestion_request_id"]),
    )
    write_audit(
        db,
        workspace_id=workspace_id,
        event_type="capture.storage_failed",
        actor_user_id=None,
        device_id=str(capture["device_id"]),
        details={
            "capture_id": capture["capture_id"],
            "error_code": error_code,
            "error_detail": error_detail,
        },
    )
    return capture_by_id(db, workspace_id, str(capture["capture_id"]))


def parse_capture_timestamp(value: object) -> tuple[datetime, tuple[int, dict[str, object]] | None]:
    text = text_or_none(value)
    if not text:
        return datetime.now(tz=UTC), error_payload(
            400,
            "invalid_capture_timestamp",
            "ingest.frame requires captured_at.",
    )
    try:
        normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(tz=UTC), error_payload(
            400,
            "invalid_capture_timestamp",
            "captured_at must be an ISO-8601 timestamp.",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    skew = abs((datetime.now(tz=UTC) - parsed).total_seconds())
    if skew > CAPTURE_CLOCK_SKEW_SECONDS:
        return parsed, error_payload(
            400,
            "invalid_capture_timestamp",
            "captured_at is outside the 10 minute MVP clock skew window.",
            max_skew_seconds=CAPTURE_CLOCK_SKEW_SECONDS,
        )
    return parsed, None


def validate_client_content_hash(
    payload: dict[str, object],
    decoded: bytes,
) -> tuple[int, dict[str, object]] | None:
    declared = text_or_none(payload.get("content_sha256") or payload.get("sha256"))
    if not declared:
        return None
    normalized = declared.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        return error_payload(400, "invalid_content_hash", "content_sha256 must be a lowercase sha256 hex digest.")
    if hashlib.sha256(decoded).hexdigest() != normalized:
        return error_payload(400, "invalid_content_hash", "content_sha256 does not match decoded content.")
    return None


def sanitized_frame_bytes(decoded: bytes, content_type: str) -> tuple[bytes, tuple[int, dict[str, object]] | None]:
    if content_type == "image/jpeg":
        if not decoded.startswith(b"\xff\xd8"):
            return b"", error_payload(400, "invalid_content_type", "content_type image/jpeg does not match JPEG bytes.")
        try:
            return strip_jpeg_exif(decoded), None
        except ValueError as exc:
            return b"", error_payload(400, "invalid_content_type", str(exc))
    if content_type == "image/png":
        if not decoded.startswith(PNG_SIGNATURE):
            return b"", error_payload(400, "invalid_content_type", "content_type image/png does not match PNG bytes.")
        try:
            return strip_png_exif(decoded), None
        except ValueError as exc:
            return b"", error_payload(400, "invalid_content_type", str(exc))
    return b"", error_payload(415, "unsupported_media_type", "Unsupported Senses frame content type.")


def sanitized_audio_bytes(decoded: bytes, content_type: str) -> tuple[bytes, tuple[int, dict[str, object]] | None]:
    if len(decoded) < MIN_AUDIO_BYTES:
        return b"", error_payload(
            400,
            "invalid_audio",
            f"Audio payload must contain at least {MIN_AUDIO_BYTES} decoded bytes.",
            min_audio_bytes=MIN_AUDIO_BYTES,
        )
    if content_type == "audio/wav" and not (decoded.startswith(b"RIFF") and decoded[8:12] == b"WAVE"):
        return b"", error_payload(400, "invalid_audio", "content_type audio/wav does not match WAV bytes.")
    if content_type == "audio/webm" and not decoded.startswith(b"\x1a\x45\xdf\xa3"):
        return b"", error_payload(400, "invalid_audio", "content_type audio/webm does not match WebM bytes.")
    if content_type == "audio/ogg" and not decoded.startswith(b"OggS"):
        return b"", error_payload(400, "invalid_audio", "content_type audio/ogg does not match Ogg bytes.")
    if content_type in {"audio/m4a", "audio/mp4"} and b"ftyp" not in decoded[:32]:
        return b"", error_payload(400, "invalid_audio", "content_type audio/mp4 audio does not match ISO-BMFF bytes.")
    if content_type in {"audio/mp3", "audio/mpeg"} and not (
        decoded.startswith(b"ID3") or (len(decoded) >= 2 and decoded[0] == 0xFF and decoded[1] & 0xE0 == 0xE0)
    ):
        return b"", error_payload(400, "invalid_audio", "content_type audio/mpeg does not match MP3 bytes.")
    if content_type == "audio/aac" and not (len(decoded) >= 2 and decoded[0] == 0xFF and decoded[1] & 0xF0 == 0xF0):
        return b"", error_payload(400, "invalid_audio", "content_type audio/aac does not match AAC ADTS bytes.")
    return decoded, None


def normalized_audio_duration_seconds(
    payload: dict[str, object],
    metadata: dict[str, object],
) -> float | tuple[int, dict[str, object]] | None:
    value = payload.get("duration_seconds")
    if value is None:
        duration_ms = payload.get("duration_ms") or metadata.get("duration_ms")
        if duration_ms is not None:
            try:
                value = float(duration_ms) / 1000.0
            except (TypeError, ValueError):
                value = None
    if value is None:
        value = metadata.get("duration_seconds")
    if value is None:
        return error_payload(
            400,
            "invalid_audio_duration",
            "ingest.audio requires duration_seconds or duration_ms so Senses can enforce bounded capture.",
            max_duration_seconds=MAX_AUDIO_DURATION_SECONDS,
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return error_payload(400, "invalid_audio_duration", "Audio duration must be numeric.")
    if parsed <= 0 or parsed > MAX_AUDIO_DURATION_SECONDS:
        return error_payload(
            413,
            "audio_duration_too_long",
            f"Audio duration must be greater than 0 and at most {MAX_AUDIO_DURATION_SECONDS} seconds.",
            max_duration_seconds=MAX_AUDIO_DURATION_SECONDS,
        )
    return round(parsed, 3)


def strip_jpeg_exif(data: bytes) -> bytes:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG payload is truncated.")
    output = bytearray(data[:2])
    index = 2
    length = len(data)
    seen_sof = False
    seen_sos = False
    seen_eoi = False
    while index < length:
        if data[index] != 0xFF:
            raise ValueError("JPEG marker is missing before scan data.")
        marker_start = index
        while index < length and data[index] == 0xFF:
            index += 1
        if index >= length:
            raise ValueError("JPEG marker is truncated.")
        marker = data[index]
        index += 1
        if marker == 0x00:
            raise ValueError("JPEG marker is invalid before scan data.")
        if marker == 0xD8:
            raise ValueError("JPEG payload contains an unexpected SOI marker.")
        if marker == 0xD9 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            output.extend(data[marker_start:index])
            if marker == 0xD9:
                seen_eoi = True
                if index != length:
                    raise ValueError("JPEG payload has trailing bytes after EOI.")
                break
            continue
        if index + 2 > length:
            raise ValueError("JPEG segment length is truncated.")
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2:
            raise ValueError("JPEG segment length is invalid.")
        segment_end = index + segment_length
        if segment_end > length:
            raise ValueError("JPEG segment extends beyond payload.")
        segment_payload = data[index + 2:segment_end]
        if marker in JPEG_START_OF_FRAME_MARKERS:
            seen_sof = True
        if marker == 0xDA:
            if not seen_sof:
                raise ValueError("JPEG start of frame is missing.")
            seen_sos = True
            output.extend(data[marker_start:segment_end])
            index = segment_end
            scan_end = jpeg_scan_end(data, index)
            output.extend(data[index:scan_end])
            index = scan_end
            continue
        if marker in JPEG_METADATA_MARKERS and (
            marker != 0xE1
            or segment_payload.startswith(b"Exif\x00\x00")
            or segment_payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00")
        ):
            index = segment_end
            continue
        output.extend(data[marker_start:segment_end])
        index = segment_end
    if not seen_sof:
        raise ValueError("JPEG start of frame is missing.")
    if not seen_sos:
        raise ValueError("JPEG start of scan is missing.")
    if not seen_eoi:
        raise ValueError("JPEG end marker is missing.")
    return bytes(output)


def jpeg_scan_end(data: bytes, index: int) -> int:
    length = len(data)
    while index < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker_start = index
        while index < length and data[index] == 0xFF:
            index += 1
        if index >= length:
            raise ValueError("JPEG scan marker is truncated.")
        marker = data[index]
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            index += 1
            continue
        return marker_start
    raise ValueError("JPEG end marker is missing.")


def strip_png_exif(data: bytes) -> bytes:
    output = bytearray(PNG_SIGNATURE)
    index = len(PNG_SIGNATURE)
    length = len(data)
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    ihdr_payload = b""
    idat_payload = bytearray()
    while index < length:
        if index + 12 > length:
            raise ValueError("PNG chunk header is truncated.")
        chunk_start = index
        chunk_length = int.from_bytes(data[index:index + 4], "big")
        chunk_type = data[index + 4:index + 8]
        if not valid_png_chunk_type(chunk_type):
            raise ValueError("PNG chunk type is invalid.")
        chunk_data_start = index + 8
        chunk_data_end = chunk_data_start + chunk_length
        chunk_end = chunk_data_end + 4
        if chunk_end > length:
            raise ValueError("PNG chunk extends beyond payload.")
        chunk_payload = data[chunk_data_start:chunk_data_end]
        expected_crc = int.from_bytes(data[chunk_data_end:chunk_end], "big")
        actual_crc = binascii.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("PNG chunk CRC is invalid.")
        if png_chunk_is_unknown_critical(chunk_type):
            raise ValueError("PNG critical chunk type is unsupported.")
        if chunk_type == b"IHDR":
            if seen_ihdr or chunk_start != len(PNG_SIGNATURE):
                raise ValueError("PNG IHDR chunk must be first.")
            if chunk_length != 13:
                raise ValueError("PNG IHDR chunk length is invalid.")
            seen_ihdr = True
            ihdr_payload = chunk_payload
        elif not seen_ihdr:
            raise ValueError("PNG IHDR chunk is missing.")
        if chunk_type == b"IDAT":
            seen_idat = True
            idat_payload.extend(chunk_payload)
        if chunk_type == b"IEND":
            if chunk_length != 0:
                raise ValueError("PNG IEND chunk length is invalid.")
            seen_iend = True
        if not png_chunk_is_ancillary(chunk_type):
            output.extend(data[index:chunk_end])
        index = chunk_end
        if chunk_type == b"IEND":
            if index != length:
                raise ValueError("PNG payload has trailing bytes after IEND.")
            break
    if not seen_ihdr:
        raise ValueError("PNG IHDR chunk is missing.")
    if not seen_idat:
        raise ValueError("PNG IDAT chunk is missing.")
    if not seen_iend:
        raise ValueError("PNG IEND chunk is missing.")
    validate_png_idat_payload(ihdr_payload, bytes(idat_payload))
    return bytes(output)


def valid_png_chunk_type(chunk_type: bytes) -> bool:
    return (
        len(chunk_type) == 4
        and all(
            65 <= byte <= 90 or 97 <= byte <= 122
            for byte in chunk_type
        )
        and not png_chunk_reserved_bit_set(chunk_type)
    )


def png_chunk_is_ancillary(chunk_type: bytes) -> bool:
    return bool(chunk_type[0] & 0x20)


def png_chunk_is_unknown_critical(chunk_type: bytes) -> bool:
    return not png_chunk_is_ancillary(chunk_type) and chunk_type not in PNG_CRITICAL_CHUNK_TYPES


def png_chunk_reserved_bit_set(chunk_type: bytes) -> bool:
    return bool(chunk_type[2] & 0x20)


def validate_png_idat_payload(ihdr_payload: bytes, idat_payload: bytes) -> None:
    width = int.from_bytes(ihdr_payload[0:4], "big")
    height = int.from_bytes(ihdr_payload[4:8], "big")
    bit_depth = ihdr_payload[8]
    color_type = ihdr_payload[9]
    compression_method = ihdr_payload[10]
    filter_method = ihdr_payload[11]
    interlace_method = ihdr_payload[12]
    if width < 1 or height < 1 or width > PNG_MAX_DIMENSION or height > PNG_MAX_DIMENSION:
        raise ValueError("PNG dimensions are invalid.")
    if color_type not in PNG_COLOR_TYPE_SAMPLES or bit_depth not in PNG_ALLOWED_BIT_DEPTHS[color_type]:
        raise ValueError("PNG color type or bit depth is unsupported.")
    if compression_method != 0 or filter_method != 0:
        raise ValueError("PNG compression or filter method is unsupported.")
    if interlace_method != 0:
        raise ValueError("PNG interlace method is unsupported.")
    bits_per_pixel = PNG_COLOR_TYPE_SAMPLES[color_type] * bit_depth
    row_bytes = (width * bits_per_pixel + 7) // 8
    expected_size = height * (1 + row_bytes)
    if expected_size > PNG_MAX_DECOMPRESSED_BYTES:
        raise ValueError("PNG decoded image is too large.")
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(idat_payload, expected_size + 1)
        if decompressor.unconsumed_tail:
            raise ValueError("PNG IDAT payload exceeds declared image dimensions.")
        decoded += decompressor.flush()
    except zlib.error as exc:
        raise ValueError("PNG IDAT payload is invalid.") from exc
    if not decompressor.eof or decompressor.unused_data:
        raise ValueError("PNG IDAT payload is invalid.")
    if len(decoded) != expected_size:
        raise ValueError("PNG IDAT payload does not match declared image dimensions.")
    row_stride = row_bytes + 1
    if any(filter_byte > 4 for filter_byte in decoded[0:expected_size:row_stride]):
        raise ValueError("PNG scanline filter is invalid.")


def capture_request_hash(value: dict[str, object]) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_content_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def bounded_identifier(value: object, *, max_length: int) -> str:
    text = text_or_none(value)
    if not text or len(text) > max_length:
        return ""
    if any(char.isspace() for char in text):
        return ""
    return text


def optional_bounded_int(value: object, *, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def optional_float(value: object, *, minimum: float, maximum: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return round(parsed, 3)


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
        "notes": ["Senses capture records exist in Phase 8; reference search and resolve remain deferred."],
    }


def dependency_resolution_payload(raw_dependencies: object) -> dict[str, object]:
    if not isinstance(raw_dependencies, dict) or not isinstance(raw_dependencies.get("dependencies"), list):
        return {
            "status": "unknown",
            "blocked_reason": "dependency_resolution_not_provided_by_host",
            "dependencies": [
                {**dependency, "status": "unknown", "selected_provider_app_ids": []}
                for dependency in DECLARED_DEPENDENCIES
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
    optional = []
    for dependency in OPTIONAL_DEPENDENCIES:
        resolved = dependencies_by_alias.get(str(dependency["alias"]))
        if isinstance(resolved, dict):
            optional.append(_compact_dependency(resolved))
        else:
            optional.append({**dependency, "status": "missing_declaration", "selected_provider_app_ids": []})
    blocked = [item for item in required if str(item.get("status")) not in {"resolved"}]
    return {
        "status": "blocked" if blocked else "resolved",
        "workspace_id": raw_dependencies.get("workspace_id"),
        "consumer_app_id": raw_dependencies.get("consumer_app_id"),
        "dependencies": [*required, *optional],
        "required_dependencies": required,
        "optional_dependencies": optional,
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
        "stale_provider_app_ids": item.get("stale_provider_app_ids") or [],
        "candidate_provider_app_ids": [
            candidate.get("app_id")
            for candidate in item.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("app_id")
        ],
        "candidates": [
            {
                "app_id": candidate.get("app_id"),
                "surfaces": candidate.get("surfaces") if isinstance(candidate.get("surfaces"), list) else [],
            }
            for candidate in item.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("app_id")
        ],
        "blocked_reason": item.get("blocked_reason"),
    }


def chat_provider_app_id_from_dependencies(dependencies: dict[str, object]) -> str | None:
    dependency = dependency_by_alias(dependencies, CHAT_COMMUNICATION_DEPENDENCY_ALIAS)
    if dependency is None:
        return None
    selected = string_items(dependency.get("selected_provider_app_ids"))
    candidates = dependency_candidate_provider_app_ids(dependency, required_surface="view")
    if selected and str(dependency.get("status") or "") == "resolved":
        return next((app_id for app_id in selected if app_id in candidates), None)
    return None


def speech_provider_app_id_from_dependencies(dependencies: dict[str, object], *, alias: str) -> str | None:
    dependency = dependency_by_alias(dependencies, alias)
    if dependency is None:
        return None
    selected = string_items(dependency.get("selected_provider_app_ids"))
    candidates = dependency_candidate_provider_app_ids(dependency, required_surface="backend")
    if selected and str(dependency.get("status") or "") == "resolved":
        return next((app_id for app_id in selected if app_id in candidates), None)
    return None


def dependency_by_alias(dependencies: dict[str, object], alias: str) -> dict[str, object] | None:
    items = dependencies.get("dependencies")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("alias") or "") == alias:
            return item
    return None


def string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (text_or_none(item) for item in value) if item]


def dependency_candidate_provider_app_ids(dependency: dict[str, object], *, required_surface: str) -> list[str]:
    candidates = dependency.get("candidates")
    if not isinstance(candidates, list):
        return []
    ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        app_id = text_or_none(candidate.get("app_id"))
        surfaces = set(string_items(candidate.get("surfaces")))
        if app_id and required_surface in surfaces:
            ids.append(app_id)
    return ids


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
    if normalized in {"ingest.frame", "ingest.audio"}:
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "captures"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "devices"},
        ]
    if normalized in {"ingest.bundle.start", "ingest.bundle_part"}:
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "bundles"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "captures"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "devices"},
        ]
    if normalized in {"storage_write.completed", SPEECH_TRANSCRIPTION_CALLBACK_ACTION}:
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "captures"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "bundles"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "devices"},
        ]
    if normalized == "background.tick":
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "captures"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "bundles"},
        ]
    if normalized in {"routing.dispatch_capture", "routing.reset"}:
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "captures"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "routing"},
        ]
    if normalized in {"routing.dispatch_bundle", RUNTIME_DISPATCH_CALLBACK_ACTION}:
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "captures"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "bundles"},
            {"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "routing"},
        ]
    if normalized in {"set_view_filter", "set_custom_view", "clear_custom_view", "view-state.changed"}:
        return [{"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": "view-state"}]
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


def pairing_completion_allowed(
    *,
    allow_member_pairing: bool,
    actor: dict[str, str | None],
    row: sqlite3.Row,
) -> bool:
    if allow_member_pairing:
        return True
    if actor_is_manager(actor):
        return True
    return str(actor.get("user_id") or "") == str(row["created_by_user_id"] or "")


def storage_pending_stale(capture: sqlite3.Row | None, timestamp: str) -> bool:
    if capture is None:
        return False
    updated_at = text_or_none(capture["updated_at"])
    if not updated_at:
        return True
    return seconds_between(updated_at, timestamp) >= STORAGE_PENDING_LEASE_SECONDS


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
