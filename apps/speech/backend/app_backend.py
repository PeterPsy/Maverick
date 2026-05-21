"""Speech app backend entrypoint."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

BACKEND_WORKER_START_TIMEOUT_SECONDS = 20
BACKEND_WORKER_REQUEST_TIMEOUT_SECONDS = 300
BACKEND_WORKER_SCRIPT = Path(__file__).with_name("backend_worker.py")
_BACKEND_WORKER_PROCESSES: dict[int, subprocess.Popen] = {}


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    try:
        response = handle_entrypoint_payload(payload)
    except Exception as error:
        if strict_backend_worker_enabled():
            raise
        response = handle_inline_payload(payload, fallback_error=error)
    _response(int(response.get("status_code") or 500), response.get("json") if isinstance(response.get("json"), dict) else {})


def handle_entrypoint_payload(payload: dict) -> dict:
    if persistent_backend_worker_enabled() and payload.get("data_root"):
        try:
            return run_backend_worker(payload)
        except Exception as error:
            if strict_backend_worker_enabled():
                raise
            return handle_inline_payload(payload, fallback_error=error)
    return handle_inline_payload(payload)


def handle_inline_payload(payload: dict, fallback_error: Exception | None = None) -> dict:
    from errors import SpeechProviderUnavailableError, SpeechTranscriptionError, SpeechValidationError, validation_error_payload
    from service import app_events_for_action, handle_action

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
        return {
            "status_code": 503,
            "json": {
                "error": "provider_unavailable",
                "detail": str(error),
            },
        }
    except SpeechTranscriptionError as error:
        return {
            "status_code": 502,
            "json": {
                "error": "transcription_failed",
                "detail": str(error),
            },
        }
    response = dict(result)
    response["app_events"] = app_events_for_action(str(body.get("action") or "capabilities").strip())
    if fallback_error is not None:
        response["backend_worker_fallback"] = f"{fallback_error.__class__.__name__}: {fallback_error}"
    return {"status_code": status_code, "json": response}


def body_from_payload(payload: dict) -> dict:
    body = dict(payload.get("body")) if isinstance(payload.get("body"), dict) else {}
    body_file = payload.get("body_file") if isinstance(payload.get("body_file"), dict) else {}
    if not body_file:
        return body
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    body.setdefault("action", str(query.get("action") or "transcribe_audio"))
    body.setdefault("content_type", str(body_file.get("content_type") or "application/octet-stream"))
    body["_body_file_path"] = str(body_file.get("path") or "")
    body["_body_file_size_bytes"] = int(body_file.get("size_bytes") or 0)
    for key in ("language", "profile"):
        if query.get(key):
            body[key] = str(query[key])
    return body


def backend_worker_mode() -> str:
    return os.environ.get("MAVERICK_SPEECH_BACKEND_WORKER", "auto").strip().lower() or "auto"


def persistent_backend_worker_enabled() -> bool:
    return backend_worker_mode() not in {"0", "false", "no", "off", "entrypoint", "process", "disabled"}


def strict_backend_worker_enabled() -> bool:
    return backend_worker_mode() == "persistent"


def run_backend_worker(payload: dict) -> dict:
    data_root = Path(str(payload.get("data_root") or "")).expanduser()
    paths = backend_worker_paths(data_root)
    ensure_backend_worker(socket_path=paths["socket"], pid_path=paths["pid"], lock_path=paths["lock"], log_path=paths["log"])
    return send_backend_worker_request(paths["socket"], payload)


def backend_worker_paths(data_root: Path) -> dict[str, Path]:
    digest = hashlib.sha256(json.dumps(backend_worker_config(), sort_keys=True).encode("utf-8")).hexdigest()[:16]
    run_dir = data_root / "run"
    return {
        "socket": run_dir / f"backend-{digest}.sock",
        "pid": run_dir / f"backend-{digest}.pid",
        "lock": run_dir / f"backend-{digest}.lock",
        "log": run_dir / f"backend-{digest}.log",
    }


def backend_worker_config() -> dict:
    paths = [
        Path(__file__),
        BACKEND_WORKER_SCRIPT,
        Path(__file__).with_name("service.py"),
        Path(__file__).with_name("engines.py"),
        Path(__file__).with_name("synthesis.py"),
        Path(__file__).with_name("transcription.py"),
        Path(__file__).with_name("settings.py"),
        Path(__file__).with_name("store.py"),
    ]
    return {
        "version": 1,
        "files": [
            {
                "name": path.name,
                "size": path.stat().st_size if path.exists() else 0,
                "mtime_ns": path.stat().st_mtime_ns if path.exists() else 0,
            }
            for path in paths
        ],
    }


def ensure_backend_worker(*, socket_path: Path, pid_path: Path, lock_path: Path, log_path: Path) -> None:
    if backend_worker_accepts_connection(socket_path):
        return
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    with locked_worker_start(lock_path):
        if backend_worker_accepts_connection(socket_path):
            return
        remove_stale_backend_worker_files(socket_path, pid_path)
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(BACKEND_WORKER_SCRIPT),
                    "--socket",
                    str(socket_path),
                    "--pid-file",
                    str(pid_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                close_fds=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + BACKEND_WORKER_START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if backend_worker_accepts_connection(socket_path):
                    _BACKEND_WORKER_PROCESSES[process.pid] = process
                    return
                if process.poll() is not None:
                    break
                time.sleep(0.1)
    raise RuntimeError("Speech backend worker did not become ready.")


def send_backend_worker_request(socket_path: Path, payload: dict) -> dict:
    deadline = time.monotonic() + BACKEND_WORKER_REQUEST_TIMEOUT_SECONDS
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            client.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
            try:
                chunk = client.recv(1024 * 1024)
            except socket.timeout:
                continue
            if not chunk:
                break
            chunks.append(chunk)
    if not chunks:
        raise RuntimeError("Speech backend worker returned an empty response.")
    response = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("Speech backend worker returned an invalid response.")
    return response


def backend_worker_accepts_connection(socket_path: Path) -> bool:
    if not socket_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(str(socket_path))
        return True
    except OSError:
        return False


def remove_stale_backend_worker_files(socket_path: Path, pid_path: Path) -> None:
    pid = read_worker_pid(pid_path)
    if pid and pid_matches_backend_worker(pid, socket_path):
        terminate_worker_pid(pid)
    for path in (socket_path, pid_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def read_worker_pid(pid_path: Path) -> int:
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def pid_matches_backend_worker(pid: int, socket_path: Path) -> bool:
    if not pid_is_alive(pid):
        return False
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        cmdline = cmdline_path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="ignore")
    except OSError:
        return False
    return "backend_worker.py" in cmdline and str(socket_path) in cmdline


def terminate_worker_pid(pid: int) -> bool:
    if not pid_is_alive(pid):
        return False
    process = _BACKEND_WORKER_PROCESSES.pop(pid, None)
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return True
        if not pid_is_alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, 9)
    except OSError:
        return False
    if process is not None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    return True


class locked_worker_start:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "locked_worker_start":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.handle is None:
            return
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        self.handle.close()


def stop_backend_workers(data_root: Path) -> dict:
    stopped: list[dict] = []
    run_dir = data_root / "run"
    for pid_path in sorted(run_dir.glob("backend-*.pid")) if run_dir.exists() else []:
        stem = pid_path.stem
        socket_path = run_dir / f"{stem}.sock"
        pid = read_worker_pid(pid_path)
        stopped.append(
            {
                "worker_id": stem,
                "pid": pid,
                "terminated": bool(pid and pid_matches_backend_worker(pid, socket_path) and terminate_worker_pid(pid)),
            }
        )
        remove_stale_backend_worker_files(socket_path, pid_path)
    return {"stopped": stopped, "count": len(stopped)}


if __name__ == "__main__":
    main()
