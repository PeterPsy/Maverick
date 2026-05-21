"""Persistent Piper TTS worker for Speech backend subprocesses."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path
import socket
import sys
import time
import wave

DEFAULT_IDLE_TIMEOUT_SECONDS = 15 * 60


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("--config-json", required=True)
    args = parser.parse_args()

    config = json.loads(args.config_json)
    serve(
        socket_path=Path(args.socket),
        pid_path=Path(args.pid_file),
        config=config,
        idle_timeout_seconds=worker_idle_timeout_seconds(),
    )


def worker_idle_timeout_seconds() -> int:
    configured = os.environ.get("MAVERICK_SPEECH_PIPER_WORKER_IDLE_SECONDS", "").strip()
    if not configured:
        return DEFAULT_IDLE_TIMEOUT_SECONDS
    try:
        return max(30, int(configured))
    except ValueError:
        return DEFAULT_IDLE_TIMEOUT_SECONDS


def serve(*, socket_path: Path, pid_path: Path, config: dict, idle_timeout_seconds: int) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass

    start = time.monotonic()
    voice = _load_piper_voice(config)
    load_seconds = time.monotonic() - start
    _log_event("voice_loaded", voice_id=str(config.get("voice_id") or ""), load_seconds=load_seconds)
    last_activity = time.monotonic()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.listen(4)
        server.settimeout(1.0)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        _log_event("started", socket_name=socket_path.name, pid=os.getpid())
        while True:
            if time.monotonic() - last_activity > idle_timeout_seconds:
                _log_event("idle_timeout", idle_timeout_seconds=idle_timeout_seconds)
                return
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                request = _read_request(connection)
                if not request:
                    continue
                last_activity = time.monotonic()
                try:
                    output_path = str(request.get("output_path") or "")
                    if output_path:
                        size_bytes = _synthesize_wav_file(voice, str(request.get("text") or ""), Path(output_path))
                        audio_base64 = ""
                    else:
                        audio = _synthesize_wav(voice, str(request.get("text") or ""))
                        size_bytes = len(audio)
                        audio_base64 = base64.b64encode(audio).decode("ascii")
                    response = {
                        "ok": True,
                        "audio_base64": audio_base64,
                        "size_bytes": size_bytes,
                        "worker": {
                            "scope": "workspace_daemon",
                            "cross_request_reuse": True,
                            "voice_load_seconds": load_seconds,
                            "ready_before_request": True,
                        },
                    }
                except Exception as error:
                    _log_event("job_failed", error_type=error.__class__.__name__, detail=str(error))
                    response = {"ok": False, "error_type": error.__class__.__name__, "detail": str(error)}
                connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        _log_event("stopped", socket_name=socket_path.name)
        server.close()
        for path in (socket_path, pid_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _load_piper_voice(config: dict) -> object:
    try:
        from piper.voice import PiperVoice
    except ImportError as error:
        raise RuntimeError("piper Python package is not installed.") from error

    model_path = str(config.get("model_path") or "")
    config_path = str(config.get("config_path") or "")
    if config_path:
        try:
            return PiperVoice.load(model_path, config_path=config_path)
        except TypeError:
            return PiperVoice.load(model_path, config_path)
    return PiperVoice.load(model_path)


def _synthesize_wav(voice: object, text: str) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize(text, wav_file)
    return buffer.getvalue()


def _synthesize_wav_file(voice: object, text: str, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    try:
        with wave.open(str(temp_path), "wb") as wav_file:
            voice.synthesize(text, wav_file)
        os.replace(temp_path, output_path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return output_path.stat().st_size


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
