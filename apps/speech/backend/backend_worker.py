"""Persistent Speech app backend worker."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

from errors import SpeechProviderUnavailableError, SpeechTranscriptionError, SpeechValidationError, validation_error_payload
from service import app_events_for_action, handle_action

DEFAULT_IDLE_TIMEOUT_SECONDS = 6 * 60 * 60


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--pid-file", required=True)
    args = parser.parse_args()
    serve(socket_path=Path(args.socket), pid_path=Path(args.pid_file), idle_timeout_seconds=worker_idle_timeout_seconds())


def worker_idle_timeout_seconds() -> int:
    configured = os.environ.get("MAVERICK_SPEECH_BACKEND_WORKER_IDLE_SECONDS", "").strip()
    if not configured:
        return DEFAULT_IDLE_TIMEOUT_SECONDS
    try:
        return max(30, int(configured))
    except ValueError:
        return DEFAULT_IDLE_TIMEOUT_SECONDS


def serve(*, socket_path: Path, pid_path: Path, idle_timeout_seconds: int) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass

    activity_lock = threading.Lock()
    last_activity = time.monotonic()
    active_requests = 0

    def begin_request() -> None:
        nonlocal active_requests, last_activity
        with activity_lock:
            active_requests += 1
            last_activity = time.monotonic()

    def finish_request() -> None:
        nonlocal active_requests, last_activity
        with activity_lock:
            active_requests = max(0, active_requests - 1)
            last_activity = time.monotonic()

    def idle_expired() -> bool:
        with activity_lock:
            return active_requests == 0 and time.monotonic() - last_activity > idle_timeout_seconds

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.listen(8)
        server.settimeout(1.0)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        _log_event("started", socket_name=socket_path.name, pid=os.getpid())
        while True:
            if idle_expired():
                _log_event("idle_timeout", idle_timeout_seconds=idle_timeout_seconds)
                return
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            begin_request()
            threading.Thread(
                target=_handle_connection,
                args=(connection, finish_request),
                daemon=True,
            ).start()
    finally:
        _log_event("stopped", socket_name=socket_path.name)
        server.close()
        for path in (socket_path, pid_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _handle_connection(connection: socket.socket, finish_request) -> None:
    try:
        with connection:
            payload = _read_request(connection)
            if not payload:
                return
            try:
                response = handle_payload(payload)
            except Exception as error:
                _log_event("request_failed", error_type=error.__class__.__name__, detail=str(error))
                response = {"status_code": 500, "json": {"error": "backend_worker_failed", "detail": str(error)}}
            connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        finish_request()


def handle_payload(payload: dict) -> dict:
    body = body_from_payload(payload)
    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            Path(payload["generated_storage_root"]),
            body,
            Path(payload["uploaded_storage_root"]) if payload.get("uploaded_storage_root") else None,
        )
    except SpeechValidationError as error:
        return {"status_code": 400, "json": validation_error_payload(error)}
    except SpeechProviderUnavailableError as error:
        return {"status_code": 503, "json": {"error": "provider_unavailable", "detail": str(error)}}
    except SpeechTranscriptionError as error:
        return {"status_code": 502, "json": {"error": "transcription_failed", "detail": str(error)}}
    response = dict(result)
    response["app_events"] = app_events_for_action(str(body.get("action") or "capabilities").strip())
    return {"status_code": status_code, "json": response}


def body_from_payload(payload: dict) -> dict:
    body = dict(payload.get("body")) if isinstance(payload.get("body"), dict) else {}
    if isinstance(payload.get("app_secrets"), dict):
        body["_app_secrets"] = dict(payload["app_secrets"])
    if isinstance(payload.get("provider_config"), dict):
        body["_provider_config"] = dict(payload["provider_config"])
    body_file = payload.get("body_file") if isinstance(payload.get("body_file"), dict) else {}
    if not body_file:
        return body
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    body.setdefault("action", str(query.get("action") or "transcribe_audio"))
    body.setdefault("content_type", str(body_file.get("content_type") or "application/octet-stream"))
    body["_body_file_path"] = str(body_file.get("path") or "")
    body["_body_file_size_bytes"] = int(body_file.get("size_bytes") or 0)
    for key in ("language", "profile", "session_id", "chunk_index", "final", "is_final", "dictation", "dictation_mode", "conversation", "conversation_mode"):
        if query.get(key):
            body[key] = str(query[key])
    return body


def _read_request(connection: socket.socket) -> dict:
    chunks: list[bytes] = []
    while True:
        chunk = connection.recv(1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    if not chunks:
        return {}
    line = b"".join(chunks).split(b"\n", 1)[0]
    try:
        payload = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _log_event(event: str, **fields: object) -> None:
    payload = {"event": event, **fields}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise
