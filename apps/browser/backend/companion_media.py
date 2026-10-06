"""Verified Storage evidence and local Speech handoffs through declared dependencies."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import time

from companion_connections import CompanionError, require_owner
from companion_store import database, encoded, public_operation, sweep
from companion_validation import instagram_url


STORAGE = "storage-file-content-write"
SPEECH = "speech-to-text"


def selected(dependencies: dict | None, alias: str) -> bool:
    return any(isinstance(d, dict) and d.get("alias") == alias and d.get("status") == "resolved"
               and d.get("selected_provider_app_ids") for d in (dependencies or {}).get("dependencies", []))


def media_bytes(item: dict, *, kind: str) -> str:
    value = item.get("base64")
    budget = 2 * 1024 * 1024 if kind == "audio" else 512 * 1024
    if not isinstance(value, str) or len(value) > (budget + 2) * 4 // 3:
        raise CompanionError("invalid_media", "The captured media exceeds its byte budget.")
    try:
        content = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise CompanionError("invalid_media", "The captured media is not valid base64.") from error
    if len(content) > budget or not content.startswith(b"\x1aE\xdf\xa3" if kind == "audio" else b"\xff\xd8\xff"):
        raise CompanionError("invalid_media", "Captured media must be JPEG or WebM tab audio.")
    return value


def prepare(db, row, result: dict, dependencies: dict | None) -> list[dict]:
    if row["action"] != "video.analyze" or result.get("error"):
        return []
    options = json.loads(row["input_json"])
    result["source_url"] = instagram_url(result.get("source_url"))
    frames = result.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= options.get("frame_count", 6):
        raise CompanionError("invalid_media", "The expected bounded video samples are missing.")
    requests = []
    operation_id = row["operation_id"]
    save = options.get("save_evidence", True)

    def add(alias, key, body, path=None):
        request_id = f"browser-{operation_id}-{key}-{alias}"
        db.execute("INSERT INTO media_requests VALUES(?,?,?,?,?,'pending')", (request_id, operation_id, key, alias, path))
        requests.append({"request_id": request_id, "dependency_alias": alias, "body": body,
                         "callback": {"action": "media.completed", "payload": {"operation_id": operation_id}}})

    def evidence(key, item, extension):
        if not save:
            return
        if not selected(dependencies, STORAGE):
            item["storage_error"] = "storage_dependency_unavailable"
            return
        path = f"storage/generated/browser/{operation_id}/{key}.{extension}"
        add(STORAGE, key, {"action": "file.content.write", "mode": "create", "workspace_relative_path": path,
                           "content_base64": item["base64"]}, path)

    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise CompanionError("invalid_media", "Each frame must be a structured capture.")
        media_bytes(frame, kind="frame")
        evidence(f"frame-{index}", frame, "jpg")
    audio = result.get("audio")
    if audio is not None:
        if not isinstance(audio, dict) or options.get("include_audio", True) is False:
            raise CompanionError("invalid_media", "Unexpected tab audio.")
        media_bytes(audio, kind="audio")
        duration = audio.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= options.get("max_seconds", 90):
            raise CompanionError("invalid_media", "Tab audio must respect the finite recording duration.")
        evidence("audio", audio, "webm")
        if selected(dependencies, SPEECH):
            result["transcription"] = {"status": "pending", "local_only": True}
            add(SPEECH, "transcription", {"action": "transcribe_audio", "audio_base64": audio["base64"],
                                         "content_type": "audio/webm", "profile": "balanced", "local_only": True})
        else:
            result["transcription"] = {"status": "unavailable", "error": "local_speech_dependency_unavailable", "local_only": True}
    return requests


def callback(data_root: Path, workspace_id: str, user_id: str | None, body: dict) -> dict:
    request_id = str(body.get("request_id") or "")
    operation_id = str(body.get("operation_id") or "")
    with database(data_root) as db:
        sweep(db, time.time())
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        pending = db.execute("SELECT * FROM media_requests WHERE request_id=? AND operation_id=?", (request_id, operation_id)).fetchone()
        if row is None or pending is None:
            raise CompanionError("media_callback_unavailable", "No matching pending media request.", 404)
        # Core callbacks omit actor payload fields; ownership is recovered from the
        # durable operation only on the trusted dependency callback surface.
        owner = db.execute("SELECT * FROM connections WHERE session_id=?", (row["session_id"],)).fetchone()
        require_owner(db, row["session_id"], workspace_id, user_id or owner["user_id"], allow_revoked=True)
        original = body.get("request")
        if body.get("dependency_alias") != pending["dependency_alias"] or not isinstance(original, dict) or original.get("request_id") != request_id or original.get("dependency_alias") != pending["dependency_alias"]:
            raise CompanionError("media_callback_invalid", "The callback does not match the requested dependency.", 403)
        if row["status"] != "processing_media" or pending["status"] != "pending":
            return public_operation(row, include_result=False)
        result = json.loads(row["result_json"])
        envelope = body.get("dependency_backend_result") or {}
        response = envelope.get("json") or {}
        succeeded = body.get("dependency_backend_status") == "completed" and not response.get("error")
        if pending["dependency_alias"] == SPEECH:
            engine = str(response.get("engine") or "")
            if succeeded and engine in {"faster-whisper", "whisper.cpp"}:
                result["transcription"] = {"status": "completed", "local_only": True, "engine": engine,
                                           "text": str(response.get("text") or "")[:50000],
                                           "language": response.get("language"), "segments": (response.get("segments") or [])[:1000]}
            else:
                result["transcription"] = {"status": "failed", "local_only": True, "error": "local_transcription_failed"}
        else:
            item = result["audio"] if pending["item_key"] == "audio" else result["frames"][int(pending["item_key"].split("-")[1])]
            file = response.get("file") or {}
            identity = file.get("file_id") or file.get("stable_storage_file_id") or file.get("id")
            path = file.get("workspace_relative_path") or response.get("workspace_relative_path")
            if succeeded and identity and path == pending["expected_path"]:
                item["storage"] = {"file_id": identity, "workspace_relative_path": path, "deep_link": f"/app/storage?file_id={identity}",
                                   "sha256": file.get("sha256") or (response.get("audit") or {}).get("sha256")}
                item.pop("base64", None)
            else:
                item["storage_error"] = "storage_evidence_write_failed"
        db.execute("UPDATE media_requests SET status='done' WHERE request_id=?", (request_id,))
        remaining = db.execute("SELECT count(*) FROM media_requests WHERE operation_id=? AND status='pending'", (operation_id,)).fetchone()[0]
        db.execute("UPDATE operations SET result_json=?,status=? WHERE operation_id=?", (encoded(result), "processing_media" if remaining else "completed", operation_id))
        updated = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return public_operation(updated, include_result=False)
