"""Phase 2 backend tests for Senses."""

from __future__ import annotations

from base64 import b64decode, b64encode
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
sys.path.insert(0, str(MAVERICK_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from core.shared.entrypoints import run_json_entrypoint
from database import WORKSPACE_TABLES, db_path, ensure_schema, table_columns
import service
from service import app_events_for_action, handle_action


def resolved_storage_dependencies() -> dict[str, object]:
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
                "candidates": [{"app_id": "storage"}],
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
                "candidates": [{"app_id": "storage"}],
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


class SensesPhase2EntrypointTest(unittest.TestCase):
    def test_schema_is_workspace_scoped_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root, "default")
            ensure_schema(data_root, "default")
            self.assertTrue(db_path(data_root).is_file())
            for table in WORKSPACE_TABLES:
                self.assertIn("workspace_id", table_columns(data_root, table))
            with sqlite3.connect(db_path(data_root)) as db:
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

    def test_manifest_reports_phase_2_surfaces(self) -> None:
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
            self.assertEqual(manifest["phase"], "phase-2")
            self.assertEqual(manifest["dependency_resolution"]["status"], "resolved")
            self.assertEqual(manifest["declared_surfaces"]["frontend"], True)
            self.assertIn("pairing.start", manifest["backend_actions"])
            self.assertIn("devices.revoke", manifest["backend_actions"])
            self.assertIn("ingest.frame", manifest["backend_actions"])
            self.assertIn("storage_write.completed", manifest["callback_actions"])
            self.assertNotIn("ingest.frame", manifest["deferred_to_later_phases"])

    def test_missing_workspace_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "health"})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "missing_workspace_id")

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

            with sqlite3.connect(db_path(data_root)) as db:
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

            with sqlite3.connect(db_path(data_root)) as db:
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
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(updated["settings"]["allow_member_pairing"])
            self.assertEqual(updated["settings"]["pairing_code_ttl_seconds"], 120)

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

            with sqlite3.connect(db_path(data_root)) as db:
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

            with sqlite3.connect(db_path(data_root)) as db:
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

            with sqlite3.connect(db_path(data_root)) as db:
                storage_file_id = db.execute(
                    "SELECT storage_file_id FROM captures WHERE capture_id = ?",
                    (accepted["capture_id"],),
                ).fetchone()[0]
            self.assertEqual(storage_file_id, file_id)

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
            self.assertEqual(cli_manifest["phase"], "phase-2")
            self.assertFalse(cli_overview["ok"])
            self.assertEqual(cli_overview["error"], "unsupported_cli_action")
            self.assertTrue(mcp_manifest["ok"])
            self.assertEqual(mcp_manifest["phase"], "phase-2")
            self.assertFalse(mcp_pairing["ok"])
            self.assertEqual(mcp_pairing["error"], "unsupported_tool")
            self.assertTrue(mcp_override["ok"])
            self.assertEqual(mcp_override["phase"], "phase-2")
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
