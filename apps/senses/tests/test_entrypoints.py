"""Phase 8 backend tests for Senses."""

from __future__ import annotations

from base64 import b64decode, b64encode
from contextlib import closing
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zlib

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
APP_ROOT = Path(__file__).resolve().parents[1]
STORAGE_ROOT = MAVERICK_ROOT / "apps" / "storage"
sys.path.insert(0, str(MAVERICK_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from core.shared.entrypoints import run_json_entrypoint
from database import WORKSPACE_TABLES, db_path, ensure_schema, table_columns
import service
from service import app_events_for_action, handle_action


def resolved_storage_dependencies(
    *,
    chat_provider_app_id: str | None = "chat",
    chat_status: str = "resolved",
    chat_candidates: list[str] | None = None,
    speech_provider_app_id: str | None = None,
    speech_status: str = "optional_unset",
    speech_candidates: list[str] | None = None,
    tts_provider_app_id: str | None = None,
    tts_status: str = "optional_unset",
    tts_candidates: list[str] | None = None,
) -> dict[str, object]:
    effective_chat_candidates = (
        chat_candidates
        if chat_candidates is not None
        else ([chat_provider_app_id] if chat_provider_app_id else [])
    )
    effective_speech_candidates = (
        speech_candidates
        if speech_candidates is not None
        else ([speech_provider_app_id] if speech_provider_app_id else [])
    )
    effective_tts_candidates = (
        tts_candidates
        if tts_candidates is not None
        else ([tts_provider_app_id] if tts_provider_app_id else [])
    )
    return {
        "workspace_id": "default",
        "consumer_app_id": "senses",
        "status": "resolved",
        "dependencies": [
            {
                "alias": "storage-file-content-write",
                "interface": "file.content.write",
                "version": "^1",
                "required": True,
                "cardinality": "one",
                "status": "resolved",
                "selected_provider_app_ids": ["storage"],
                "candidates": [{"app_id": "storage", "surfaces": ["backend", "view"]}],
                "blocked_reason": None,
            },
            {
                "alias": "storage-file-catalog",
                "interface": "file.catalog",
                "version": "^1",
                "required": True,
                "cardinality": "one",
                "status": "resolved",
                "selected_provider_app_ids": ["storage"],
                "candidates": [{"app_id": "storage", "surfaces": ["backend", "view"]}],
                "blocked_reason": None,
            },
            {
                "alias": "chat-communication",
                "interface": "communication.chat",
                "version": "^1",
                "required": False,
                "cardinality": "one",
                "status": chat_status,
                "selected_provider_app_ids": [chat_provider_app_id] if chat_provider_app_id and chat_status == "resolved" else [],
                "stale_provider_app_ids": [],
                "candidates": [
                    {"app_id": app_id, "surfaces": ["backend", "view"]}
                    for app_id in effective_chat_candidates
                ],
                "blocked_reason": None,
            },
            {
                "alias": "speech-to-text",
                "interface": "speech.transcription",
                "version": "^1",
                "required": False,
                "cardinality": "one",
                "status": speech_status,
                "selected_provider_app_ids": [speech_provider_app_id] if speech_provider_app_id and speech_status == "resolved" else [],
                "stale_provider_app_ids": [],
                "candidates": [
                    {"app_id": app_id, "surfaces": ["backend", "cli", "mcp"]}
                    for app_id in effective_speech_candidates
                ],
                "blocked_reason": None,
            },
            {
                "alias": "text-to-speech",
                "interface": "speech.synthesis",
                "version": "^1",
                "required": False,
                "cardinality": "one",
                "status": tts_status,
                "selected_provider_app_ids": [tts_provider_app_id] if tts_provider_app_id and tts_status == "resolved" else [],
                "stale_provider_app_ids": [],
                "candidates": [
                    {"app_id": app_id, "surfaces": ["backend"]}
                    for app_id in effective_tts_candidates
                ],
                "blocked_reason": None,
            },
        ],
    }


def actor(user_id: str = "user-1", workspace_role: str = "member") -> dict[str, str | None]:
    return {
        "user_id": user_id,
        "workspace_role": workspace_role,
        "platform_role": "member",
        "effective_mode": "sandbox",
    }


def run_hook(relative_path: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(MAVERICK_ROOT)
        if not env.get("PYTHONPATH")
        else f"{MAVERICK_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, relative_path],
        cwd=APP_ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def run_storage_backend(workspace_root: Path, body: dict[str, object]) -> dict[str, object]:
    uploaded_root = workspace_root / "storage" / "uploaded"
    generated_root = workspace_root / "storage" / "generated"
    uploaded_root.mkdir(parents=True, exist_ok=True)
    generated_root.mkdir(parents=True, exist_ok=True)
    return run_json_entrypoint(
        STORAGE_ROOT / "backend" / "app_backend.py",
        cwd=STORAGE_ROOT,
        payload={
            "app_id": "storage",
            "workspace_id": "default",
            "consumer_app_id": "senses",
            "dependency_alias": "storage-file-content-write",
            "surface": "dependency_backend_request",
            "data_root": str(workspace_root / "data" / "storage"),
            "uploaded_storage_root": str(uploaded_root),
            "generated_storage_root": str(generated_root),
            "body": body,
        },
    )


def start_and_complete_device(data_root: Path, user_id: str = "user-1") -> dict[str, object]:
    status, started = handle_action(
        data_root,
        {"action": "pairing.start", "_workspace_id": "default", "_app_actor": actor(user_id)},
    )
    if status != 201:
        raise AssertionError(started)
    status, completed = handle_action(
        data_root,
        {
            "action": "pairing.complete",
            "_workspace_id": "default",
            "_app_actor": actor(user_id),
            "code": started["pairing"]["code"],
            "device_display_name": "Marco iPhone",
            "device_kind": "ios",
            "platform": "ios",
            "client_device_id": "ios-client-1",
        },
    )
    if status != 200:
        raise AssertionError(completed)
    return completed


def jpeg_with_exif() -> bytes:
    exif_payload = b"Exif\x00\x00GPSSECRET"
    app1 = b"\xff\xe1" + (len(exif_payload) + 2).to_bytes(2, "big") + exif_payload
    jfif_payload = b"JFIF\x00"
    app0 = b"\xff\xe0" + (len(jfif_payload) + 2).to_bytes(2, "big") + jfif_payload
    dqt_payload = b"\x00" + bytes([1] * 64)
    dqt = b"\xff\xdb" + (len(dqt_payload) + 2).to_bytes(2, "big") + dqt_payload
    sof0_payload = b"\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    sof0 = b"\xff\xc0" + (len(sof0_payload) + 2).to_bytes(2, "big") + sof0_payload
    sos_payload = b"\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00"
    sos = b"\xff\xda" + (len(sos_payload) + 2).to_bytes(2, "big") + sos_payload
    return b"\xff\xd8" + app1 + app0 + dqt + sof0 + sos + b"\x11\x22\xff\xd9"


def png_chunk(chunk_type: bytes, payload: bytes = b"") -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + chunk_type + payload + crc.to_bytes(4, "big")


def png_with_text_metadata(*, filter_byte: int = 0, extra_chunks: tuple[bytes, ...] = ()) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )
    idat = zlib.compress(bytes([filter_byte, 0, 0, 0, 0]))
    return (
        signature
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"tEXt", b"GPS=secret")
        + png_chunk(b"eXIf", b"Exif\x00\x00GPSSECRET")
        + b"".join(extra_chunks)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND")
    )


def wav_audio() -> bytes:
    payload = bytes([0] * 160)
    return b"RIFF" + (len(payload) + 36).to_bytes(4, "little") + b"WAVEfmt " + bytes([0] * 28) + b"data" + len(payload).to_bytes(4, "little") + payload


def capture_request(
    completed: dict[str, object],
    *,
    request_id: str = "req-1",
    idempotency_key: str = "idem-1",
    content: bytes | None = None,
    content_type: str = "image/jpeg",
    prompt: str = "Cosa sto guardando?",
) -> dict[str, object]:
    body = content if content is not None else jpeg_with_exif()
    return {
        "action": "ingest.frame",
        "_workspace_id": "default",
        "_app_actor": actor(),
        "_app_dependencies": resolved_storage_dependencies(),
        "schema_version": "senses.capture.v1",
        "request_id": request_id,
        "device_id": completed["device"]["device_id"],
        "device_session_id": completed["device_session"]["device_session_id"],
        "idempotency_key": idempotency_key,
        "client_capture_id": "ios-local-1",
        "input_mode": "vision.snapshot",
        "prompt": prompt,
        "content_type": content_type,
        "content_base64": b64encode(body).decode("ascii"),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "captured_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "metadata": {"adapter_id": "meta_glasses", "width": 1600, "height": 1200},
    }


def audio_request(
    completed: dict[str, object],
    *,
    request_id: str = "audio-req-1",
    idempotency_key: str = "audio-idem-1",
    content: bytes | None = None,
    content_type: str = "audio/wav",
    prompt: str = "Cosa ho appena chiesto?",
    dependencies: dict[str, object] | None = None,
    duration_seconds: float | None = 1.2,
) -> dict[str, object]:
    body = content if content is not None else wav_audio()
    payload: dict[str, object] = {
        "action": "ingest.audio",
        "_workspace_id": "default",
        "_app_actor": actor(),
        "_app_dependencies": dependencies or resolved_storage_dependencies(),
        "schema_version": "senses.audio.v1",
        "request_id": request_id,
        "device_id": completed["device"]["device_id"],
        "device_session_id": completed["device_session"]["device_session_id"],
        "idempotency_key": idempotency_key,
        "client_capture_id": "ios-audio-local-1",
        "input_mode": "audio.push_to_talk",
        "prompt": prompt,
        "content_type": content_type,
        "content_base64": b64encode(body).decode("ascii"),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "captured_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "metadata": {"adapter_id": "meta_glasses", "origin_label": "Occhiali"},
    }
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    return payload


def bundle_start_request(
    completed: dict[str, object],
    *,
    bundle_id: str = "bundle-1",
    request_id: str = "bundle-start-1",
    dependencies: dict[str, object] | None = None,
    include_device: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": "ingest.bundle.start",
        "_workspace_id": "default",
        "_app_actor": actor(),
        "_app_dependencies": dependencies or resolved_storage_dependencies(),
        "schema_version": "senses.bundle.v1",
        "bundle_id": bundle_id,
        "request_id": request_id,
        "metadata": {"adapter_id": "meta_glasses", "origin_label": "Occhiali"},
    }
    if include_device:
        payload["device_id"] = completed["device"]["device_id"]
        payload["device_session_id"] = completed["device_session"]["device_session_id"]
    return payload


def bundle_frame_part_request(
    completed: dict[str, object],
    *,
    bundle_id: str = "bundle-1",
    request_id: str = "bundle-frame-1",
    idempotency_key: str = "bundle-frame-1",
) -> dict[str, object]:
    payload = capture_request(
        completed,
        request_id=request_id,
        idempotency_key=idempotency_key,
        prompt="",
    )
    payload["action"] = "ingest.bundle_part"
    payload["bundle_id"] = bundle_id
    payload["role"] = "frame"
    return payload


def bundle_audio_part_request(
    completed: dict[str, object],
    *,
    bundle_id: str = "bundle-1",
    request_id: str = "bundle-audio-1",
    idempotency_key: str = "bundle-audio-1",
    dependencies: dict[str, object] | None = None,
    include_device: bool = True,
) -> dict[str, object]:
    payload = audio_request(
        completed,
        request_id=request_id,
        idempotency_key=idempotency_key,
        prompt="",
        dependencies=dependencies,
    )
    payload["action"] = "ingest.bundle_part"
    payload["bundle_id"] = bundle_id
    payload["role"] = "audio"
    if not include_device:
        payload.pop("device_id", None)
        payload.pop("device_session_id", None)
    return payload


def storage_callback_payload(
    accepted: dict[str, object],
    *,
    request_id: str | None = None,
    provider_app_id: str | None = "storage",
    dependency_status: str = "completed",
    file_id: str | None = None,
) -> dict[str, object]:
    capture_id = str(accepted["capture_id"])
    storage = accepted["storage"]
    expected_request_id = request_id or f"write-{capture_id}"
    result: dict[str, object] = {}
    if dependency_status == "completed":
        result = {
            "status_code": 200,
            "json": {
                "file": {
                    "file_id": file_id or f"generated:senses/{capture_id}",
                    "workspace_relative_path": storage["workspace_relative_path"],
                    "sha256": storage["sha256"],
                    "size_bytes": storage["size_bytes"],
                },
                "bytes_written": storage["size_bytes"],
            },
        }
        if provider_app_id is not None:
            result["dependency_provider_app_id"] = provider_app_id
    return {
        "action": "storage_write.completed",
        "_workspace_id": "default",
        "_app_surface": "dependency_backend_request_callback",
        "capture_id": capture_id,
        "request_id": expected_request_id,
        "dependency_alias": "storage-file-content-write",
        "dependency_backend_status": dependency_status,
        "dependency_backend_result": result,
        "request": {
            "request_id": expected_request_id,
            "dependency_alias": "storage-file-content-write",
        },
    }


def stored_capture(
    data_root: Path,
    completed: dict[str, object],
    *,
    request_id: str = "stored-1",
    idempotency_key: str = "stored-1",
    prompt: str = "Cosa sto guardando?",
) -> dict[str, object]:
    status, accepted = handle_action(
        data_root,
        capture_request(
            completed,
            request_id=request_id,
            idempotency_key=idempotency_key,
            prompt=prompt,
        ),
    )
    if status != 202:
        raise AssertionError(accepted)
    status, stored = handle_action(
        data_root,
        storage_callback_payload(
            accepted,
            file_id=f"generated:senses/{accepted['capture_id']}",
        ),
    )
    if status != 200:
        raise AssertionError(stored)
    return stored["capture"]


def runtime_callback_payload(
    dispatch: dict[str, object],
    *,
    runtime_session_id: str = "runtime-session-1",
    turn_id: str = "turn-1",
    runtime_status: str = "submitted",
    error: str = "",
) -> dict[str, object]:
    attempt = dispatch["runtime_dispatch_attempt"]
    request = dispatch["runtime_launch_requests"][0]
    callback_payload = {}
    if isinstance(request, dict) and isinstance(request.get("callback"), dict):
        raw_callback_payload = request["callback"].get("payload")
        if isinstance(raw_callback_payload, dict):
            callback_payload = raw_callback_payload
    payload = {
        "action": "runtime_dispatch.completed",
        "_workspace_id": "default",
        "_app_surface": "runtime_request_callback",
        "_app_dependencies": resolved_storage_dependencies(),
        "capture_id": dispatch["capture_id"],
        "attempt_id": attempt["attempt_id"],
        "request_id": attempt["request_id"],
        "runtime_request_status": runtime_status,
        "runtime_session_id": runtime_session_id,
        "turn_id": turn_id,
        "error": error,
        "request": request,
    }
    if callback_payload.get("bundle_id"):
        payload["bundle_id"] = callback_payload["bundle_id"]
    return payload


class SensesPhase8EntrypointTest(unittest.TestCase):
    def test_schema_is_workspace_scoped_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root, "default")
            ensure_schema(data_root, "default")
            self.assertTrue(db_path(data_root).is_file())
            for table in WORKSPACE_TABLES:
                self.assertIn("workspace_id", table_columns(data_root, table))
            with closing(sqlite3.connect(db_path(data_root))) as db:
                settings_count = db.execute(
                    "SELECT COUNT(*) FROM settings WHERE workspace_id = ?",
                    ("default",),
                ).fetchone()[0]
                table_names = {
                    row[0]
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
            self.assertEqual(settings_count, 1)
            self.assertTrue(set(WORKSPACE_TABLES).issubset(table_names))

    def test_manifest_reports_phase_7_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = handle_action(
                Path(tmp),
                {
                    "action": "manifest",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": resolved_storage_dependencies(),
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(manifest["action"], "manifest")
            self.assertIs(manifest["ok"], True)
            self.assertIs(manifest["available"], True)
            self.assertEqual(manifest["phase"], "phase-8")
            self.assertIs(manifest["auth"]["user_session_ingest_supported"], True)
            self.assertIs(manifest["auth"]["raw_device_auth_supported"], False)
            self.assertNotIn("device_ingress_supported", manifest["auth"])
            self.assertNotIn("device_token_ingress", manifest["auth"])
            self.assertEqual(manifest["dependency_resolution"]["status"], "resolved")
            self.assertEqual(manifest["declared_surfaces"]["frontend"], True)
            self.assertEqual(manifest["declared_surfaces"]["mcp"], list(service.DECLARED_MCP_TOOLS))
            self.assertEqual(manifest["auth"]["view_state_policy"]["mutate"], "workspace_admin")
            self.assertIn("pairing.start", manifest["backend_actions"])
            self.assertIn("devices.revoke", manifest["backend_actions"])
            self.assertIn("captures.get", manifest["backend_actions"])
            self.assertIn("captures.bundle_get", manifest["backend_actions"])
            self.assertIn("ingest.bundle.start", manifest["backend_actions"])
            self.assertIn("ingest.bundle_part", manifest["backend_actions"])
            self.assertIn("ingest.frame", manifest["backend_actions"])
            self.assertIn("ingest.audio", manifest["backend_actions"])
            self.assertIn("routing.dispatch_bundle", manifest["backend_actions"])
            self.assertIn("routing.dispatch_capture", manifest["backend_actions"])
            self.assertIn("routing.reset", manifest["backend_actions"])
            self.assertIn("storage_write.completed", manifest["callback_actions"])
            self.assertIn("runtime_dispatch.completed", manifest["callback_actions"])
            self.assertNotIn("ingest.frame", manifest["deferred_to_later_phases"])
            self.assertNotIn("routing.dispatch_capture", manifest["deferred_to_later_phases"])

    def test_manifest_reports_unavailable_when_dependencies_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = handle_action(
                Path(tmp),
                {
                    "action": "manifest",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": {"dependencies": []},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(manifest["action"], "manifest")
            self.assertIs(manifest["ok"], False)
            self.assertIs(manifest["available"], False)
            self.assertEqual(manifest["dependency_resolution"]["status"], "blocked")

    def test_missing_workspace_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "health"})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "missing_workspace_id")

    def test_view_state_requires_authenticated_actor_and_admin_for_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, unauthenticated = handle_action(
                data_root,
                {"action": "view_filter", "_workspace_id": "default"},
            )
            self.assertEqual(status, 401)
            self.assertEqual(unauthenticated["error"], "authentication_required")

            status, forbidden = handle_action(
                data_root,
                {
                    "action": "set_view_filter",
                    "_workspace_id": "default",
                    "_app_actor": actor("member-1", "member"),
                    "tab": "captures",
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(forbidden["error"], "senses_permission_forbidden")

            status, default_state = handle_action(
                data_root,
                {
                    "action": "view_filter",
                    "_workspace_id": "default",
                    "_app_actor": actor("member-1", "member"),
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(default_state["state"]["view_filter"]["tab"], "devices")

            status, updated = handle_action(
                data_root,
                {
                    "action": "set_view_filter",
                    "_workspace_id": "default",
                    "_app_actor": actor("admin-1", "admin"),
                    "tab": "captures",
                    "query": "receipt",
                    "capture_filter": "chat-linked",
                    "routing_filter": "task",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(updated["state"]["view_filter"]["tab"], "captures")
            self.assertEqual(updated["state"]["view_filter"]["query"], "receipt")
            self.assertEqual(updated["state"]["view_filter"]["capture_filter"], "chat-linked")
            self.assertEqual(updated["state"]["view_filter"]["routing_filter"], "task")

    def test_chat_link_requires_resolved_selected_dependency(self) -> None:
        resolved = service.dependency_resolution_payload(resolved_storage_dependencies(chat_provider_app_id="chat"))
        provider_app_id = service.chat_provider_app_id_from_dependencies(resolved)
        linked = service.chat_link_payload("thread-1", provider_app_id=provider_app_id)

        self.assertEqual(provider_app_id, "chat")
        self.assertTrue(linked["available"])
        self.assertEqual(linked["deep_link"], "/app/chat/threads/thread-1")

        missing = service.dependency_resolution_payload(
            resolved_storage_dependencies(chat_provider_app_id=None, chat_status="optional_unset", chat_candidates=[])
        )
        unavailable = service.chat_link_payload(
            "thread-1",
            provider_app_id=service.chat_provider_app_id_from_dependencies(missing),
        )
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertIsNone(unavailable["deep_link"])

        optional_unset = service.dependency_resolution_payload(
            resolved_storage_dependencies(
                chat_provider_app_id=None,
                chat_status="optional_unset",
                chat_candidates=["workspace-chat"],
            )
        )
        optional_unset_link = service.chat_link_payload(
            "thread-1",
            provider_app_id=service.chat_provider_app_id_from_dependencies(optional_unset),
        )
        self.assertFalse(optional_unset_link["available"])
        self.assertEqual(optional_unset_link["status"], "unavailable")
        self.assertIsNone(optional_unset_link["deep_link"])

    def test_pairing_start_and_complete_registers_device_without_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, started = handle_action(
                data_root,
                {"action": "pairing.start", "_workspace_id": "default", "_app_actor": actor()},
            )
            self.assertEqual(status, 201)
            self.assertEqual(started["pairing"]["status"], "pending")
            self.assertRegex(started["pairing"]["code"], r"^[A-Z2-9]{8}$")
            self.assertEqual(started["pairing"]["qr_payload"]["backend_action"], "pairing.complete")

            status, completed = handle_action(
                data_root,
                {
                    "action": "pairing.complete",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "code": started["pairing"]["code"],
                    "device_display_name": "Marco iPhone",
                    "client_device_id": "client-123",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(completed["device"]["status"], "active")
            self.assertEqual(completed["device"]["owner_user_id"], "user-1")
            self.assertEqual(completed["device_session"]["auth_mode"], "user_session_mvp")
            self.assertNotIn("device_token", json.dumps(completed))
            self.assertEqual(
                [event["resource"] for event in app_events_for_action("pairing.complete")],
                ["pairing", "devices"],
            )

    def test_pairing_complete_is_one_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, started = handle_action(
                data_root,
                {"action": "pairing.start", "_workspace_id": "default", "_app_actor": actor()},
            )
            self.assertEqual(status, 201)

            complete_payload = {
                "action": "pairing.complete",
                "_workspace_id": "default",
                "_app_actor": actor(),
                "code": started["pairing"]["code"],
                "device_display_name": "Marco iPhone",
            }
            status, first = handle_action(data_root, dict(complete_payload))
            self.assertEqual(status, 200)

            status, second = handle_action(data_root, dict(complete_payload))
            self.assertEqual(status, 404)
            self.assertEqual(second["error"], "invalid_or_expired_pairing_code")

            with closing(sqlite3.connect(db_path(data_root))) as db:
                device_count = db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
                session_count = db.execute("SELECT COUNT(*) FROM device_sessions").fetchone()[0]
                pairing = db.execute(
                    "SELECT status, device_id FROM pairing_sessions WHERE pairing_id = ?",
                    (started["pairing"]["pairing_id"],),
                ).fetchone()
            self.assertEqual(device_count, 1)
            self.assertEqual(session_count, 1)
            self.assertEqual(pairing, ("completed", first["device"]["device_id"]))

            status, listed = handle_action(
                data_root,
                {"action": "devices.list", "_workspace_id": "default", "_app_actor": actor()},
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(listed["devices"]), 1)
            self.assertEqual(listed["devices"][0]["display_name"], "Marco iPhone")

    def test_pairing_complete_respects_admin_only_pairing_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            admin_actor = actor("admin-1", "admin")
            status, updated = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": admin_actor,
                    "allow_member_pairing": False,
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(updated["settings"]["allow_member_pairing"])

            status, started = handle_action(
                data_root,
                {"action": "pairing.start", "_workspace_id": "default", "_app_actor": admin_actor},
            )
            self.assertEqual(status, 201)

            status, denied = handle_action(
                data_root,
                {
                    "action": "pairing.complete",
                    "_workspace_id": "default",
                    "_app_actor": actor("user-2"),
                    "code": started["pairing"]["code"],
                    "device_display_name": "Unexpected iPhone",
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(denied["error"], "senses_permission_forbidden")

            status, completed = handle_action(
                data_root,
                {
                    "action": "pairing.complete",
                    "_workspace_id": "default",
                    "_app_actor": admin_actor,
                    "code": started["pairing"]["code"],
                    "device_display_name": "Admin iPhone",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(completed["device"]["owner_user_id"], "admin-1")

    def test_pairing_complete_allows_creator_member_after_policy_is_tightened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            creator_actor = actor("user-1")
            admin_actor = actor("admin-1", "admin")

            status, started = handle_action(
                data_root,
                {"action": "pairing.start", "_workspace_id": "default", "_app_actor": creator_actor},
            )
            self.assertEqual(status, 201)

            status, updated = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": admin_actor,
                    "allow_member_pairing": False,
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(updated["settings"]["allow_member_pairing"])

            status, completed = handle_action(
                data_root,
                {
                    "action": "pairing.complete",
                    "_workspace_id": "default",
                    "_app_actor": creator_actor,
                    "code": started["pairing"]["code"],
                    "device_display_name": "Creator iPhone",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(completed["device"]["owner_user_id"], "user-1")

    def test_user_visibility_and_admin_include_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            start_and_complete_device(data_root, user_id="user-1")

            status, member_list = handle_action(
                data_root,
                {"action": "devices.list", "_workspace_id": "default", "_app_actor": actor("user-2")},
            )
            self.assertEqual(status, 200)
            self.assertEqual(member_list["devices"], [])

            status, admin_list = handle_action(
                data_root,
                {
                    "action": "devices.list",
                    "_workspace_id": "default",
                    "_app_actor": actor("admin-1", "admin"),
                    "include_all": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(admin_list["devices"]), 1)
            self.assertTrue(admin_list["devices"][0]["can_revoke"])

    def test_owner_can_revoke_device_and_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            device_id = completed["device"]["device_id"]

            status, revoked = handle_action(
                data_root,
                {
                    "action": "devices.revoke",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "device_id": device_id,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(revoked["device"]["status"], "revoked")

            with closing(sqlite3.connect(db_path(data_root))) as db:
                session_status = db.execute(
                    "SELECT status FROM device_sessions WHERE device_id = ?",
                    (device_id,),
                ).fetchone()[0]
            self.assertEqual(session_status, "revoked")

    def test_settings_update_requires_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, denied = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "allow_member_pairing": False,
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(denied["error"], "senses_permission_forbidden")

            status, updated = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": actor("admin-1", "admin"),
                    "allow_member_pairing": False,
                    "pairing_code_ttl_seconds": 120,
                    "routing_followup_window_seconds": 180,
                    "default_retention_class": "diagnostic",
                    "failed_capture_ttl_seconds": 900,
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(updated["settings"]["allow_member_pairing"])
            self.assertEqual(updated["settings"]["pairing_code_ttl_seconds"], 120)
            self.assertEqual(updated["settings"]["routing_followup_window_seconds"], 180)
            self.assertEqual(updated["settings"]["default_retention_class"], "diagnostic")
            self.assertEqual(updated["settings"]["failed_capture_ttl_seconds"], 900)

    def test_ingest_frame_persists_capture_and_requests_storage_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)

            status, accepted = handle_action(data_root, capture_request(completed))

            self.assertEqual(status, 202)
            self.assertTrue(accepted["ok"])
            self.assertEqual(accepted["schema_version"], "senses.capture.accepted.v1")
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(accepted["storage"]["status"], "pending")
            self.assertEqual(accepted["dispatch"]["action"], "routing.dispatch_capture")
            self.assertNotIn("runtime_launch_requests", accepted)

            requests = accepted["dependency_backend_requests"]
            self.assertEqual(len(requests), 1)
            storage_request = requests[0]
            self.assertEqual(storage_request["dependency_alias"], "storage-file-content-write")
            self.assertEqual(storage_request["body"]["action"], "file.content.write")
            self.assertEqual(storage_request["body"]["mode"], "create")
            self.assertEqual(storage_request["callback"]["action"], "storage_write.completed")
            self.assertEqual(storage_request["callback"]["payload"]["capture_id"], accepted["capture_id"])
            self.assertIn(f"/{accepted['capture_id']}.jpg", storage_request["body"]["workspace_relative_path"])

            sanitized = b64decode(storage_request["body"]["content_base64"])
            self.assertNotIn(b"Exif\x00\x00", sanitized)
            self.assertNotIn(b"GPSSECRET", sanitized)
            self.assertEqual(hashlib.sha256(sanitized).hexdigest(), accepted["storage"]["sha256"])
            self.assertEqual(len(sanitized), accepted["storage"]["size_bytes"])

            with closing(sqlite3.connect(db_path(data_root))) as db:
                ingestion = db.execute(
                    "SELECT status, capture_id FROM ingestion_requests WHERE request_id = ?",
                    ("req-1",),
                ).fetchone()
                capture = db.execute(
                    "SELECT status, storage_file_id, workspace_relative_path, sha256, size_bytes FROM captures WHERE capture_id = ?",
                    (accepted["capture_id"],),
                ).fetchone()
            self.assertEqual(ingestion, ("storage_pending", accepted["capture_id"]))
            self.assertEqual(capture[0], "storage_pending")
            self.assertIsNone(capture[1])
            self.assertEqual(capture[2], accepted["storage"]["workspace_relative_path"])
            self.assertEqual(capture[3], accepted["storage"]["sha256"])
            self.assertEqual(capture[4], accepted["storage"]["size_bytes"])

    def test_ingest_frame_rejects_invalid_media_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)

            invalid_jpeg = capture_request(
                completed,
                request_id="invalid-jpeg",
                idempotency_key="invalid-jpeg",
                content=b"\xff\xd8not-a-real-image",
            )
            status, jpeg_error = handle_action(data_root, invalid_jpeg)
            self.assertEqual(status, 400)
            self.assertEqual(jpeg_error["error"], "invalid_content_type")

            invalid_png = capture_request(
                completed,
                request_id="invalid-png",
                idempotency_key="invalid-png",
                content=b"\x89PNG\r\n\x1a\n",
                content_type="image/png",
            )
            status, png_error = handle_action(data_root, invalid_png)
            self.assertEqual(status, 400)
            self.assertEqual(png_error["error"], "invalid_content_type")

            invalid_png_filter = capture_request(
                completed,
                request_id="invalid-png-filter",
                idempotency_key="invalid-png-filter",
                content=png_with_text_metadata(filter_byte=9),
                content_type="image/png",
            )
            status, png_filter_error = handle_action(data_root, invalid_png_filter)
            self.assertEqual(status, 400)
            self.assertEqual(png_filter_error["error"], "invalid_content_type")

            invalid_png_chunk = capture_request(
                completed,
                request_id="invalid-png-chunk",
                idempotency_key="invalid-png-chunk",
                content=png_with_text_metadata(extra_chunks=(png_chunk(b"IDaT"),)),
                content_type="image/png",
            )
            status, png_chunk_error = handle_action(data_root, invalid_png_chunk)
            self.assertEqual(status, 400)
            self.assertEqual(png_chunk_error["error"], "invalid_content_type")

            unknown_critical_chunk = capture_request(
                completed,
                request_id="unknown-critical-png-chunk",
                idempotency_key="unknown-critical-png-chunk",
                content=png_with_text_metadata(extra_chunks=(png_chunk(b"ABCD"),)),
                content_type="image/png",
            )
            status, unknown_critical_error = handle_action(data_root, unknown_critical_chunk)
            self.assertEqual(status, 400)
            self.assertEqual(unknown_critical_error["error"], "invalid_content_type")

    def test_ingest_frame_strips_png_metadata_before_storage_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)

            status, accepted = handle_action(
                data_root,
                capture_request(
                    completed,
                    request_id="png-meta",
                    idempotency_key="png-meta",
                    content=png_with_text_metadata(),
                    content_type="image/png",
                ),
            )

            self.assertEqual(status, 202)
            storage_request = accepted["dependency_backend_requests"][0]
            sanitized = b64decode(storage_request["body"]["content_base64"])
            self.assertTrue(sanitized.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertNotIn(b"tEXt", sanitized)
            self.assertNotIn(b"eXIf", sanitized)
            self.assertNotIn(b"GPS=secret", sanitized)
            self.assertNotIn(b"GPSSECRET", sanitized)
            self.assertEqual(hashlib.sha256(sanitized).hexdigest(), accepted["storage"]["sha256"])
            self.assertEqual(len(sanitized), accepted["storage"]["size_bytes"])

    def test_ingest_audio_accepts_bounded_audio_without_speech_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)

            status, accepted = handle_action(data_root, audio_request(completed))

            self.assertEqual(status, 202)
            self.assertEqual(accepted["schema_version"], "senses.audio.accepted.v1")
            self.assertEqual(accepted["status"], "accepted")
            self.assertEqual(accepted["transcription"]["status"], "unavailable")
            self.assertEqual(len(accepted["dependency_backend_requests"]), 1)
            storage_request = accepted["dependency_backend_requests"][0]
            self.assertEqual(storage_request["dependency_alias"], "storage-file-content-write")
            self.assertTrue(accepted["storage"]["workspace_relative_path"].endswith(".wav"))
            stored_audio = b64decode(storage_request["body"]["content_base64"])
            self.assertTrue(stored_audio.startswith(b"RIFF"))
            self.assertEqual(hashlib.sha256(stored_audio).hexdigest(), accepted["storage"]["sha256"])

            with closing(sqlite3.connect(db_path(data_root))) as db:
                capture = db.execute(
                    "SELECT input_mode, content_type, metadata_json FROM captures WHERE capture_id = ?",
                    (accepted["capture_id"],),
                ).fetchone()
            self.assertEqual(capture[0], "audio.push_to_talk")
            self.assertEqual(capture[1], "audio/wav")
            metadata = json.loads(capture[2])
            self.assertEqual(metadata["duration_seconds"], 1.2)
            self.assertNotIn("transcription", metadata)

    def test_ingest_audio_claims_speech_dependency_after_storage_and_dispatches_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            dependencies = resolved_storage_dependencies(
                speech_provider_app_id="speech",
                speech_status="resolved",
            )

            status, accepted = handle_action(
                data_root,
                audio_request(
                    completed,
                    request_id="audio-with-speech",
                    idempotency_key="audio-with-speech",
                    dependencies=dependencies,
                ),
            )
            self.assertEqual(status, 202)
            self.assertEqual(accepted["transcription"]["status"], "pending")
            self.assertEqual(accepted["transcription"]["provider_app_id"], "speech")
            self.assertEqual(
                [request["dependency_alias"] for request in accepted["dependency_backend_requests"]],
                ["storage-file-content-write"],
            )

            status, stored = handle_action(
                data_root,
                storage_callback_payload(
                    accepted,
                    file_id=f"generated:senses/{accepted['capture_id']}",
                ),
            )
            self.assertEqual(status, 200)
            self.assertEqual(stored["capture"]["status"], "stored")

            status, tick = service.background_tick(data_root, "default", dependencies)
            self.assertEqual(status, 200)
            self.assertEqual(tick["status"], "queued")
            self.assertEqual(len(tick["dependency_backend_requests"]), 1)
            speech_request = tick["dependency_backend_requests"][0]
            self.assertEqual(speech_request["dependency_alias"], "speech-to-text")
            self.assertEqual(speech_request["body"]["action"], "transcribe_file")
            self.assertEqual(speech_request["body"]["workspace_relative_path"], accepted["storage"]["workspace_relative_path"])
            self.assertEqual(speech_request["body"]["content_type"], "audio/wav")
            self.assertEqual(speech_request["callback"]["action"], "speech_transcription.completed")

            status, transcribed = handle_action(
                data_root,
                {
                    "action": "speech_transcription.completed",
                    "_workspace_id": "default",
                    "_app_surface": "dependency_backend_request_callback",
                    "_app_dependencies": dependencies,
                    "capture_id": accepted["capture_id"],
                    "request_id": speech_request["request_id"],
                    "dependency_alias": "speech-to-text",
                    "dependency_backend_status": "completed",
                    "dependency_backend_result": {
                        "status_code": 200,
                        "dependency_provider_app_id": "speech",
                        "json": {
                            "job_id": "stt_test",
                            "text": "ciao Maverick",
                            "language": "it",
                            "duration_seconds": 1.2,
                        },
                    },
                    "request": speech_request,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(transcribed["transcription"]["status"], "completed")
            self.assertEqual(transcribed["transcription"]["text"], "ciao Maverick")

            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": dependencies,
                    "capture_id": accepted["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)
            runtime_request = dispatch["runtime_launch_requests"][0]
            self.assertIn("Transcript: ciao Maverick", runtime_request["input_text"])
            self.assertEqual(runtime_request["attachments"][0]["content_type"], "audio/wav")
            self.assertIn("domanda vocale", runtime_request["title"])

    def test_bundle_frame_audio_transcript_dispatches_one_multimodal_runtime_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            dependencies = resolved_storage_dependencies(
                speech_provider_app_id="speech",
                speech_status="resolved",
            )

            status, started = handle_action(
                data_root,
                bundle_start_request(completed, dependencies=dependencies, include_device=False),
            )
            self.assertEqual(status, 201)
            self.assertEqual(started["bundle"]["status"], "started")

            status, replayed_start = handle_action(
                data_root,
                bundle_start_request(completed, dependencies=dependencies, include_device=False),
            )
            self.assertEqual(status, 200)
            self.assertEqual(replayed_start["bundle"]["status"], "started")
            self.assertIsNone(replayed_start["bundle"]["device_id"])

            status, frame_part = handle_action(data_root, bundle_frame_part_request(completed))
            self.assertEqual(status, 202)
            self.assertEqual(frame_part["role"], "frame")
            status, stored_frame = handle_action(data_root, storage_callback_payload(frame_part))
            self.assertEqual(status, 200)
            self.assertEqual(stored_frame["capture"]["status"], "stored")

            status, audio_part = handle_action(
                data_root,
                bundle_audio_part_request(completed, dependencies=dependencies, include_device=False),
            )
            self.assertEqual(status, 202)
            self.assertEqual(audio_part["role"], "audio")
            status, stored_audio = handle_action(data_root, storage_callback_payload(audio_part))
            self.assertEqual(status, 200)
            self.assertEqual(stored_audio["capture"]["status"], "stored")

            status, blocked = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_bundle",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": dependencies,
                    "bundle_id": "bundle-1",
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 409)
            self.assertEqual(blocked["error"], "invalid_bundle_state")
            self.assertEqual(blocked["readiness"]["blocking_code"], "transcription_pending")

            status, tick = service.background_tick(data_root, "default", dependencies)
            self.assertEqual(status, 200)
            self.assertEqual(tick["status"], "queued")
            speech_request = tick["dependency_backend_requests"][0]

            status, transcribed = handle_action(
                data_root,
                {
                    "action": "speech_transcription.completed",
                    "_workspace_id": "default",
                    "_app_surface": "dependency_backend_request_callback",
                    "_app_dependencies": dependencies,
                    "capture_id": audio_part["capture_id"],
                    "request_id": speech_request["request_id"],
                    "dependency_alias": "speech-to-text",
                    "dependency_backend_status": "completed",
                    "dependency_backend_result": {
                        "status_code": 200,
                        "dependency_provider_app_id": "speech",
                        "json": {
                            "job_id": "stt_bundle",
                            "text": "che prezzo ha questo prodotto?",
                            "language": "it",
                            "duration_seconds": 1.2,
                        },
                    },
                    "request": speech_request,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(transcribed["transcription"]["status"], "completed")

            status, fetched = handle_action(
                data_root,
                {
                    "action": "captures.bundle_get",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": dependencies,
                    "bundle_id": "bundle-1",
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(fetched["readiness"]["ready"])
            self.assertEqual(fetched["readiness"]["transcript"], "che prezzo ha questo prodotto?")

            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_bundle",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": dependencies,
                    "bundle_id": "bundle-1",
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)
            self.assertEqual(dispatch["status"], "dispatch_pending")
            runtime_request = dispatch["runtime_launch_requests"][0]
            self.assertIn("Richiesta vocale trascritta:\nche prezzo ha questo prodotto?", runtime_request["input_text"])
            self.assertIn("Usa l'immagine allegata come contesto visivo", runtime_request["input_text"])
            self.assertNotIn("What am I looking at?", runtime_request["input_text"])
            self.assertEqual([item["content_type"] for item in runtime_request["attachments"]], ["image/jpeg", "audio/wav"])
            self.assertEqual(runtime_request["callback"]["payload"]["bundle_id"], "bundle-1")
            self.assertEqual(runtime_request["app_references"][0]["entity_type"], "capture_bundle")

            status, callback = handle_action(
                data_root,
                runtime_callback_payload(dispatch, runtime_session_id="runtime-bundle-1", turn_id="turn-bundle-1"),
            )
            self.assertEqual(status, 200)
            self.assertEqual(callback["status"], "submitted")

            status, after_callback = handle_action(
                data_root,
                {
                    "action": "captures.bundle_get",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": dependencies,
                    "bundle_id": "bundle-1",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(after_callback["bundle"]["status"], "dispatched")
            self.assertEqual(after_callback["bundle"]["thread_id"], "runtime-bundle-1")
            self.assertEqual(after_callback["chat"]["deep_link"], "/app/chat/threads/runtime-bundle-1")

    def test_ingest_audio_requires_bounded_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)

            status, missing = handle_action(
                data_root,
                audio_request(completed, request_id="audio-no-duration", idempotency_key="audio-no-duration", duration_seconds=None),
            )
            self.assertEqual(status, 400)
            self.assertEqual(missing["error"], "invalid_audio_duration")

            status, too_long = handle_action(
                data_root,
                audio_request(completed, request_id="audio-too-long", idempotency_key="audio-too-long", duration_seconds=61),
            )
            self.assertEqual(status, 413)
            self.assertEqual(too_long["error"], "audio_duration_too_long")

    def test_ingest_frame_idempotency_success_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            request = capture_request(completed)

            status, first = handle_action(data_root, dict(request))
            self.assertEqual(status, 202)
            status, replay = handle_action(data_root, dict(request))
            self.assertEqual(status, 200)
            self.assertEqual(replay["capture_id"], first["capture_id"])
            self.assertNotIn("dependency_backend_requests", replay)

            conflict_request = dict(request)
            conflict_request["prompt"] = "Payload diverso"
            status, conflict = handle_action(data_root, conflict_request)
            self.assertEqual(status, 409)
            self.assertEqual(conflict["error"], "idempotency_conflict")

    def test_ingest_frame_reissues_stale_pending_with_upsert_when_storage_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            storage_workspace = Path(tmp) / "storage-workspace"
            completed = start_and_complete_device(data_root)
            request = capture_request(completed)

            status, first = handle_action(data_root, dict(request))
            self.assertEqual(status, 202)
            original_request = first["dependency_backend_requests"][0]
            self.assertEqual(original_request["body"]["mode"], "create")
            first_storage = run_storage_backend(storage_workspace, original_request["body"])
            self.assertEqual(first_storage["status_code"], 200)
            self.assertEqual(
                first_storage["json"]["file"]["workspace_relative_path"],
                first["storage"]["workspace_relative_path"],
            )

            stale_at = (
                datetime.now(tz=UTC)
                - timedelta(seconds=service.STORAGE_PENDING_LEASE_SECONDS + 5)
            ).isoformat()
            db = sqlite3.connect(db_path(data_root))
            try:
                db.execute(
                    "UPDATE captures SET updated_at = ? WHERE capture_id = ?",
                    (stale_at, first["capture_id"]),
                )
                db.commit()
            finally:
                db.close()

            status, replay = handle_action(data_root, dict(request))
            self.assertEqual(status, 200)
            self.assertEqual(replay["capture_id"], first["capture_id"])
            self.assertEqual(replay["storage"]["status"], "pending")
            self.assertIn("dependency_backend_requests", replay)
            self.assertEqual(len(replay["dependency_backend_requests"]), 1)
            reissued = replay["dependency_backend_requests"][0]
            self.assertEqual(reissued["request_id"], original_request["request_id"])
            self.assertEqual(reissued["body"]["mode"], "upsert")
            self.assertIs(reissued["body"]["confirm"], True)
            self.assertEqual(
                reissued["body"]["workspace_relative_path"],
                original_request["body"]["workspace_relative_path"],
            )
            self.assertEqual(reissued["body"]["content_base64"], original_request["body"]["content_base64"])

            second_storage = run_storage_backend(storage_workspace, reissued["body"])
            self.assertEqual(second_storage["status_code"], 200)
            self.assertEqual(
                second_storage["json"]["file"]["workspace_relative_path"],
                first["storage"]["workspace_relative_path"],
            )
            self.assertEqual(second_storage["json"]["file"]["sha256"], first["storage"]["sha256"])
            self.assertEqual(
                second_storage["json"]["audit"]["previous_sha256"],
                first["storage"]["sha256"],
            )

            callback = storage_callback_payload(replay)
            callback["dependency_backend_result"] = {
                **second_storage,
                "dependency_provider_app_id": "storage",
            }
            status, stored = handle_action(data_root, callback)
            self.assertEqual(status, 200)
            self.assertEqual(stored["status"], "stored")
            self.assertEqual(stored["capture"]["storage"]["status"], "stored")
            self.assertEqual(stored["capture"]["storage"]["sha256"], first["storage"]["sha256"])

    def test_storage_write_callback_marks_capture_stored_without_runtime_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            request = capture_request(completed)
            status, accepted = handle_action(data_root, dict(request))
            self.assertEqual(status, 202)

            file_id = f"generated:senses/{accepted['capture_id']}"
            status, callback = handle_action(
                data_root,
                storage_callback_payload(accepted, file_id=file_id),
            )

            self.assertEqual(status, 200)
            self.assertTrue(callback["ok"])
            self.assertEqual(callback["status"], "stored")
            self.assertEqual(callback["capture"]["storage"]["storage_file_id"], file_id)
            self.assertNotIn("runtime_launch_requests", callback)

            with closing(sqlite3.connect(db_path(data_root))) as db:
                stored = db.execute(
                    "SELECT status, storage_file_id FROM captures WHERE capture_id = ?",
                    (accepted["capture_id"],),
                ).fetchone()
                ingestion_status = db.execute(
                    "SELECT status FROM ingestion_requests WHERE capture_id = ?",
                    (accepted["capture_id"],),
                ).fetchone()[0]
            self.assertEqual(stored, ("stored", file_id))
            self.assertEqual(ingestion_status, "stored")

            status, replay = handle_action(data_root, dict(request))
            self.assertEqual(status, 200)
            self.assertEqual(replay["storage"]["status"], "stored")
            self.assertEqual(replay["storage"]["storage_file_id"], file_id)

            status, public_callback = handle_action(
                data_root,
                {
                    "action": "storage_write.completed",
                    "_workspace_id": "default",
                    "capture_id": accepted["capture_id"],
                    "dependency_alias": "storage-file-content-write",
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(public_callback["error"], "senses_permission_forbidden")

    def test_storage_write_callback_accepts_dependency_provider_and_rejects_stale_replays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            status, accepted = handle_action(data_root, capture_request(completed))
            self.assertEqual(status, 202)

            status, wrong_request = handle_action(
                data_root,
                storage_callback_payload(accepted, request_id="write-other-capture"),
            )
            self.assertEqual(status, 400)
            self.assertEqual(wrong_request["error"], "invalid_dependency_callback")

            status, missing_provider = handle_action(
                data_root,
                storage_callback_payload(accepted, provider_app_id=None),
            )
            self.assertEqual(status, 400)
            self.assertEqual(missing_provider["error"], "invalid_dependency_callback")

            file_id = f"generated:senses/{accepted['capture_id']}"
            status, stored = handle_action(
                data_root,
                storage_callback_payload(
                    accepted,
                    provider_app_id="storage-compatible",
                    file_id=file_id,
                ),
            )
            self.assertEqual(status, 200)
            self.assertEqual(stored["status"], "stored")

            status, stale = handle_action(
                data_root,
                storage_callback_payload(accepted, file_id=f"generated:senses/{accepted['capture_id']}-replacement"),
            )
            self.assertEqual(status, 409)
            self.assertEqual(stale["error"], "invalid_capture_state")

            with closing(sqlite3.connect(db_path(data_root))) as db:
                storage_file_id = db.execute(
                    "SELECT storage_file_id FROM captures WHERE capture_id = ?",
                    (accepted["capture_id"],),
                ).fetchone()[0]
            self.assertEqual(storage_file_id, file_id)

    def test_routing_dispatch_capture_emits_runtime_launch_request_for_stored_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            capture = stored_capture(data_root, completed)

            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture["capture_id"],
                },
            )

            self.assertEqual(status, 202)
            self.assertTrue(dispatch["ok"])
            self.assertEqual(dispatch["status"], "dispatch_pending")
            self.assertEqual(dispatch["routing"]["route_kind"], "primary")
            self.assertEqual(dispatch["routing"]["target_thread_kind"], "new_primary")
            self.assertEqual(dispatch["chat"]["available"], False)
            self.assertEqual(dispatch["chat"]["status"], "pending")
            self.assertEqual(len(dispatch["runtime_launch_requests"]), 1)
            self.assertNotIn("dependency_backend_requests", dispatch)

            runtime_request = dispatch["runtime_launch_requests"][0]
            self.assertEqual(runtime_request["agent_id"], "chat")
            self.assertEqual(runtime_request["agent_type_id"], "chat")
            self.assertEqual(runtime_request["requested_mode"], "sandbox")
            self.assertEqual(runtime_request["title"], "Occhiali - domanda visiva")
            self.assertIn("Origin: Occhiali", runtime_request["input_text"])
            self.assertIn(capture["capture_id"], runtime_request["input_text"])
            self.assertEqual(runtime_request["attachments"][0]["workspace_relative_path"], capture["storage"]["workspace_relative_path"])
            self.assertEqual(runtime_request["attachments"][0]["content_type"], "image/jpeg")
            self.assertEqual(runtime_request["callback"]["action"], "runtime_dispatch.completed")
            self.assertEqual(runtime_request["callback"]["payload"]["capture_id"], capture["capture_id"])

            with closing(sqlite3.connect(db_path(data_root))) as db:
                attempt = db.execute(
                    """
                    SELECT status, route_kind, target_thread_kind, retry_count
                    FROM runtime_dispatch_attempts
                    WHERE capture_id = ?
                    """,
                    (capture["capture_id"],),
                ).fetchone()
                routing_count = db.execute("SELECT COUNT(*) FROM routing_sessions").fetchone()[0]
                capture_runtime = db.execute(
                    "SELECT runtime_session_id, turn_id FROM captures WHERE capture_id = ?",
                    (capture["capture_id"],),
                ).fetchone()
            self.assertEqual(attempt, ("pending", "primary", "new_primary", 0))
            self.assertEqual(routing_count, 1)
            self.assertEqual(capture_runtime, (None, None))
            self.assertEqual(
                [event["resource"] for event in app_events_for_action("routing.dispatch_capture")],
                ["captures", "routing"],
            )

    def test_routing_reset_clears_user_routing_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            capture = stored_capture(data_root, completed)

            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture["capture_id"],
                },
            )
            self.assertEqual(status, 202)
            routing_session_id = dispatch["routing_session"]["routing_session_id"]

            with closing(sqlite3.connect(db_path(data_root))) as db:
                db.execute(
                    """
                    UPDATE routing_sessions
                    SET primary_thread_id = 'thread_one',
                        primary_runtime_session_id = 'runtime_one',
                        active_task_thread_id = 'thread_task',
                        active_task_runtime_session_id = 'runtime_task',
                        last_capture_id = ?,
                        last_thread_id = 'thread_one',
                        last_turn_id = 'turn_one',
                        last_routing_kind = 'primary'
                    WHERE routing_session_id = ?
                    """,
                    (capture["capture_id"], routing_session_id),
                )
                db.commit()

            status, reset = handle_action(
                data_root,
                {
                    "action": "routing.reset",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "routing_session_id": routing_session_id,
                },
            )
            self.assertEqual(status, 200)
            session = reset["routing_session"]
            self.assertIsNone(session["primary_thread_id"])
            self.assertIsNone(session["active_task_thread_id"])
            self.assertIsNone(session["last_turn_id"])
            self.assertEqual(
                [event["resource"] for event in app_events_for_action("routing.reset")],
                ["captures", "routing"],
            )

    def test_routing_dispatch_blocks_second_capture_while_session_thread_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            first_capture = stored_capture(data_root, completed)
            second_capture = stored_capture(
                data_root,
                completed,
                request_id="stored-2",
                idempotency_key="stored-2",
                prompt="E questo?",
            )

            status, first = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": first_capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)

            status, blocked = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": second_capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 409)
            self.assertEqual(blocked["error"], "dispatch_in_progress")
            self.assertEqual(blocked["attempt"]["attempt_id"], first["runtime_dispatch_attempt"]["attempt_id"])
            self.assertEqual(
                blocked["attempt"]["routing_session_id"],
                first["runtime_dispatch_attempt"]["routing_session_id"],
            )

            status, callback = handle_action(
                data_root,
                runtime_callback_payload(first, runtime_session_id="runtime-session-1", turn_id="turn-1"),
            )
            self.assertEqual(status, 200)
            self.assertEqual(callback["status"], "submitted")

            status, followup = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": second_capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)
            self.assertEqual(followup["routing"]["route_kind"], "followup")
            self.assertEqual(followup["runtime_launch_requests"][0]["runtime_session_id"], "runtime-session-1")

    def test_runtime_dispatch_callback_persists_chat_thread_and_followup_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            first_capture = stored_capture(data_root, completed)
            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": first_capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)

            status, callback = handle_action(
                data_root,
                runtime_callback_payload(dispatch, runtime_session_id="runtime-session-1", turn_id="turn-1"),
            )

            self.assertEqual(status, 200)
            self.assertTrue(callback["ok"])
            self.assertEqual(callback["status"], "submitted")
            self.assertEqual(callback["capture"]["runtime_session_id"], "runtime-session-1")
            self.assertEqual(callback["capture"]["thread_id"], "runtime-session-1")
            self.assertEqual(callback["capture"]["turn_id"], "turn-1")
            self.assertEqual(callback["capture"]["origin"]["kind"], "meta_glasses")
            self.assertEqual(callback["capture"]["origin"]["label"], "Occhiali")
            self.assertEqual(callback["chat"]["status"], "linked")
            self.assertEqual(callback["chat"]["deep_link"], "/app/chat/threads/runtime-session-1")
            self.assertEqual(callback["routing_session"]["primary_runtime_session_id"], "runtime-session-1")
            self.assertEqual(callback["routing_session"]["primary_chat"]["status"], "linked")
            self.assertEqual(callback["routing_session"]["last_thread_id"], "runtime-session-1")
            self.assertEqual(callback["routing_session"]["last_turn_id"], "turn-1")

            status, fetched = handle_action(
                data_root,
                {
                    "action": "captures.get",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": resolved_storage_dependencies(),
                    "capture_id": first_capture["capture_id"],
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(fetched["capture"]["chat"]["deep_link"], "/app/chat/threads/runtime-session-1")
            self.assertEqual(fetched["runtime_dispatch_attempts"][0]["status"], "submitted")

            second_capture = stored_capture(
                data_root,
                completed,
                request_id="stored-2",
                idempotency_key="stored-2",
                prompt="E questo?",
            )
            status, followup = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": second_capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)
            self.assertEqual(followup["routing"]["route_kind"], "followup")
            self.assertEqual(followup["runtime_launch_requests"][0]["runtime_session_id"], "runtime-session-1")
            self.assertNotIn("agent_id", followup["runtime_launch_requests"][0])

            task_capture = stored_capture(
                data_root,
                completed,
                request_id="stored-3",
                idempotency_key="stored-3",
                prompt="Analizza in dettaglio questa scena e prepara un piano operativo con rischi e priorita.",
            )
            status, task_dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": task_capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)
            self.assertEqual(task_dispatch["routing"]["route_kind"], "task")
            self.assertEqual(task_dispatch["routing"]["target_thread_kind"], "new_task")
            self.assertIn("agent_id", task_dispatch["runtime_launch_requests"][0])

    def test_runtime_dispatch_callback_ignores_terminal_attempt_with_different_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            capture = stored_capture(data_root, completed)
            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)

            status, submitted = handle_action(
                data_root,
                runtime_callback_payload(dispatch, runtime_session_id="runtime-session-1", turn_id="turn-1"),
            )
            self.assertEqual(status, 200)
            self.assertEqual(submitted["status"], "submitted")

            status, stale = handle_action(
                data_root,
                runtime_callback_payload(
                    dispatch,
                    runtime_status="failed",
                    runtime_session_id="",
                    turn_id="",
                    error="late provider failure",
                ),
            )
            self.assertEqual(status, 200)
            self.assertEqual(stale["status"], "submitted")
            self.assertEqual(stale["runtime_dispatch_attempt"]["status"], "submitted")
            self.assertEqual(stale["runtime_dispatch_attempt"]["turn_id"], "turn-1")
            self.assertEqual(stale["capture"]["runtime_session_id"], "runtime-session-1")
            self.assertIsNone(stale["capture"]["error_code"])

    def test_routing_dispatch_rejects_unstored_wrong_user_and_duplicate_pending_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            status, accepted = handle_action(data_root, capture_request(completed))
            self.assertEqual(status, 202)

            status, unstored = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": accepted["capture_id"],
                },
            )
            self.assertEqual(status, 409)
            self.assertEqual(unstored["error"], "invalid_capture_state")

            status, stored = handle_action(data_root, storage_callback_payload(accepted))
            self.assertEqual(status, 200)
            capture_id = stored["capture"]["capture_id"]

            status, forbidden = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor("user-2"),
                    "capture_id": capture_id,
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(forbidden["error"], "senses_permission_forbidden")

            status, first = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture_id,
                },
            )
            self.assertEqual(status, 202)
            status, duplicate = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture_id,
                },
            )
            self.assertEqual(status, 409)
            self.assertEqual(duplicate["error"], "dispatch_in_progress")
            self.assertEqual(duplicate["attempt"]["attempt_id"], first["runtime_dispatch_attempt"]["attempt_id"])

    def test_runtime_dispatch_failure_is_recorded_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            capture = stored_capture(data_root, completed)
            status, dispatch = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)

            status, failed = handle_action(
                data_root,
                runtime_callback_payload(
                    dispatch,
                    runtime_status="failed",
                    runtime_session_id="",
                    turn_id="",
                    error="provider unavailable",
                ),
            )
            self.assertEqual(status, 200)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["runtime_dispatch_attempt"]["status"], "failed")
            self.assertEqual(failed["capture"]["error_code"], "runtime_dispatch_failed")

            status, retry = handle_action(
                data_root,
                {
                    "action": "routing.dispatch_capture",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "capture_id": capture["capture_id"],
                    "agent_id": "chat",
                },
            )
            self.assertEqual(status, 202)
            self.assertEqual(retry["runtime_dispatch_attempt"]["retry_count"], 1)

    def test_ingest_frame_validation_and_authorization_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)

            unauthenticated = capture_request(completed)
            unauthenticated["_app_actor"] = actor("")
            status, denied = handle_action(data_root, unauthenticated)
            self.assertEqual(status, 401)
            self.assertEqual(denied["error"], "authentication_required")

            wrong_user = capture_request(completed)
            wrong_user["_app_actor"] = actor("user-2")
            status, forbidden = handle_action(data_root, wrong_user)
            self.assertEqual(status, 403)
            self.assertEqual(forbidden["error"], "device_not_authorized")

            invalid_base64 = capture_request(completed)
            invalid_base64["content_base64"] = "not base64"
            status, invalid = handle_action(data_root, invalid_base64)
            self.assertEqual(status, 400)
            self.assertEqual(invalid["error"], "invalid_base64")

            unsupported = capture_request(completed)
            unsupported["content_type"] = "image/gif"
            status, unsupported_payload = handle_action(data_root, unsupported)
            self.assertEqual(status, 415)
            self.assertEqual(unsupported_payload["error"], "unsupported_media_type")

            too_old = capture_request(completed)
            too_old["captured_at"] = (datetime.now(tz=UTC) - timedelta(minutes=15)).isoformat()
            status, timestamp = handle_action(data_root, too_old)
            self.assertEqual(status, 400)
            self.assertEqual(timestamp["error"], "invalid_capture_timestamp")

            too_large = capture_request(completed, idempotency_key="large", request_id="large")
            too_large["content_base64"] = b64encode(b"\xff\xd8" + b"x" * 128).decode("ascii")
            too_large["content_sha256"] = hashlib.sha256(b"\xff\xd8" + b"x" * 128).hexdigest()
            status, _updated = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": actor("admin-1", "admin"),
                    "max_frame_bytes": 16,
                },
            )
            self.assertEqual(status, 200)
            status, large = handle_action(data_root, too_large)
            self.assertEqual(status, 413)
            self.assertEqual(large["error"], "capture_too_large")

    def test_ingest_frame_rate_limit_is_persisted_per_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            previous_limit = service.FRAME_RATE_LIMIT_MAX
            service.FRAME_RATE_LIMIT_MAX = 1
            try:
                status, first = handle_action(
                    data_root,
                    capture_request(completed, request_id="rate-1", idempotency_key="rate-1"),
                )
                self.assertEqual(status, 202)
                self.assertTrue(first["ok"])
                status, limited = handle_action(
                    data_root,
                    capture_request(completed, request_id="rate-2", idempotency_key="rate-2"),
                )
            finally:
                service.FRAME_RATE_LIMIT_MAX = previous_limit
            self.assertEqual(status, 429)
            self.assertEqual(limited["error"], "rate_limited")

    def test_ingest_frame_rate_limit_counts_storage_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            previous_limit = service.FRAME_RATE_LIMIT_MAX
            service.FRAME_RATE_LIMIT_MAX = 1
            try:
                status, first = handle_action(
                    data_root,
                    capture_request(completed, request_id="failed-rate-1", idempotency_key="failed-rate-1"),
                )
                self.assertEqual(status, 202)
                status, failed = handle_action(
                    data_root,
                    storage_callback_payload(first, dependency_status="failed"),
                )
                self.assertEqual(status, 200)
                self.assertEqual(failed["status"], "storage_failed")

                status, limited = handle_action(
                    data_root,
                    capture_request(completed, request_id="failed-rate-2", idempotency_key="failed-rate-2"),
                )
            finally:
                service.FRAME_RATE_LIMIT_MAX = previous_limit
            self.assertEqual(status, 429)
            self.assertEqual(limited["error"], "rate_limited")

    def test_cli_and_mcp_expose_only_non_user_session_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli_manifest = run_json_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "arguments": {"action": "manifest"},
                },
            )
            cli_overview = run_json_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "arguments": {"action": "overview"},
                },
            )
            mcp_manifest = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "tool_name": "senses_operations_manifest",
                    "arguments": {},
                },
            )
            mcp_pairing = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "tool_name": "senses_pairing_start",
                    "arguments": {},
                },
            )
            mcp_override = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "user_id": "user-1",
                    "workspace_role": "member",
                    "platform_role": "member",
                    "app_dependencies": resolved_storage_dependencies(),
                    "tool_name": "senses_operations_manifest",
                    "arguments": {"action": "pairing.start"},
                },
            )
            self.assertTrue(cli_manifest["ok"])
            self.assertEqual(cli_manifest["phase"], "phase-8")
            self.assertIs(cli_manifest["auth"]["user_session_ingest_supported"], True)
            self.assertIs(cli_manifest["auth"]["raw_device_auth_supported"], False)
            self.assertNotIn("device_ingress_supported", cli_manifest["auth"])
            self.assertNotIn("device_token_ingress", cli_manifest["auth"])
            self.assertFalse(cli_overview["ok"])
            self.assertEqual(cli_overview["error"], "unsupported_cli_action")
            self.assertTrue(mcp_manifest["ok"])
            self.assertEqual(mcp_manifest["phase"], "phase-8")
            self.assertIs(mcp_manifest["auth"]["user_session_ingest_supported"], True)
            self.assertIs(mcp_manifest["auth"]["raw_device_auth_supported"], False)
            self.assertNotIn("device_ingress_supported", mcp_manifest["auth"])
            self.assertNotIn("device_token_ingress", mcp_manifest["auth"])
            self.assertFalse(mcp_pairing["ok"])
            self.assertEqual(mcp_pairing["error"], "unsupported_tool")
            self.assertTrue(mcp_override["ok"])
            self.assertEqual(mcp_override["phase"], "phase-8")
            self.assertNotIn("pairing", mcp_override)
            self.assertFalse(db_path(Path(tmp)).exists())

    def test_mcp_rejects_unknown_tool_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "tool_name": "senses_unknown",
                    "arguments": {},
                },
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "unsupported_tool")

    def test_mcp_view_state_mutation_requires_admin_actor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            member_result = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "user_id": "member-1",
                    "workspace_role": "member",
                    "platform_role": "member",
                    "tool_name": "senses_set_view_filter",
                    "arguments": {"tab": "captures"},
                },
            )
            admin_result = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "user_id": "admin-1",
                    "workspace_role": "admin",
                    "platform_role": "member",
                    "tool_name": "senses_set_view_filter",
                    "arguments": {"tab": "captures"},
                },
            )
            self.assertFalse(member_result["ok"])
            self.assertEqual(member_result["error"], "senses_permission_forbidden")
            self.assertTrue(admin_result["ok"])
            self.assertEqual(admin_result["state"]["view_filter"]["tab"], "captures")

    def test_health_documents_missing_dependency_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, health = handle_action(Path(tmp), {"action": "health", "_workspace_id": "default"})
            self.assertEqual(status, 200)
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "dependency_resolution_pending")
            self.assertEqual(health["storage"]["database"]["primary_path"], "data/senses/senses.sqlite")
            self.assertNotIn("path", health["storage"]["database"])
            self.assertEqual(health["dependencies"]["status"], "unknown")
            self.assertEqual(
                health["dependencies"]["blocked_reason"],
                "dependency_resolution_not_provided_by_host",
            )

    def test_health_hook_fails_probe_when_dependencies_are_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_hook(
                "hooks/health_check.py",
                {
                    "workspace_id": "default",
                    "app_id": "senses",
                    "data_root": tmp,
                    "hook_name": "health_check",
                },
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "dependency_resolution_pending")
            self.assertEqual(payload["dependencies"]["status"], "unknown")

    def test_health_hook_allows_install_sequence_without_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_hook(
                "hooks/health_check.py",
                {
                    "workspace_id": "default",
                    "app_id": "senses",
                    "data_root": tmp,
                    "hook_name": "install",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertNotIn("dependencies", payload)

    def test_reference_manifest_defers_reference_search_after_capture_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "reference_manifest", "_workspace_id": "default"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["entity_types"], [])
            self.assertIn("capture", payload["notes"][0])


if __name__ == "__main__":
    unittest.main()
