"""Deepgram Flux realtime speech session support."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import socket
import ssl
import struct
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from errors import SpeechProviderUnavailableError, SpeechTranscriptionError, SpeechValidationError
from engines import DEEPGRAM_CONVERSATION_MODEL, deepgram_model_for

REMOTE_FLUX_TIMEOUT_SECONDS = 45
FLUX_DRAIN_SECONDS = 0.15
FLUX_FINAL_DRAIN_SECONDS = 1.0
DEFAULT_FLUX_SESSION_IDLE_SECONDS = 90
DEFAULT_FLUX_SESSION_MAX_AGE_SECONDS = 10 * 60
DEFAULT_FLUX_SESSION_PRUNE_INTERVAL_SECONDS = 15
DEFAULT_FLUX_MAX_SESSIONS = 32


def _configured_int(name: str, default: int, *, minimum: int) -> int:
    configured = os.environ.get(name, "").strip()
    if not configured:
        return default
    try:
        return max(minimum, int(configured))
    except ValueError:
        return default


class FluxWebSocketClient:
    """Small WebSocket client sufficient for Deepgram Listen v2 binary audio."""

    def __init__(self, url: str, *, headers: dict[str, str], timeout: float = REMOTE_FLUX_TIMEOUT_SECONDS) -> None:
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self._socket: socket.socket | None = None

    def connect(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "wss" or not parsed.hostname:
            raise SpeechTranscriptionError("Deepgram Flux requires a wss:// endpoint.")
        port = parsed.port or 443
        raw_socket = socket.create_connection((parsed.hostname, port), timeout=self.timeout)
        tls_socket = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=parsed.hostname)
        tls_socket.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        target = urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))
        request_lines = [
            f"GET {target} HTTP/1.1",
            f"Host: {parsed.hostname}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            *[f"{name}: {value}" for name, value in self.headers.items()],
            "",
            "",
        ]
        tls_socket.sendall("\r\n".join(request_lines).encode("utf-8"))
        response = self._read_http_response(tls_socket)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise SpeechTranscriptionError("Deepgram Flux WebSocket upgrade failed.")
        expected_accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if expected_accept.lower().encode("ascii") not in response.lower():
            raise SpeechTranscriptionError("Deepgram Flux WebSocket accept header was invalid.")
        self._socket = tls_socket

    def send_binary(self, data: bytes) -> None:
        self._send_frame(0x2, data)

    def send_json(self, payload: dict[str, object]) -> None:
        self._send_frame(0x1, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def receive_json(self, timeout: float) -> dict[str, object] | None:
        if self._socket is None:
            return None
        self._socket.settimeout(max(0.01, timeout))
        opcode, payload = self._receive_frame()
        if opcode == 0x8:
            return None
        if opcode not in {0x1, 0x2}:
            return None
        try:
            event = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return event if isinstance(event, dict) else None

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._socket is None:
            raise SpeechTranscriptionError("Deepgram Flux WebSocket is not connected.")
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length <= 0xFFFF:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(header + mask + masked)

    def _receive_frame(self) -> tuple[int, bytes]:
        if self._socket is None:
            raise SpeechTranscriptionError("Deepgram Flux WebSocket is not connected.")
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, length: int) -> bytes:
        if self._socket is None:
            raise SpeechTranscriptionError("Deepgram Flux WebSocket is not connected.")
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise SpeechTranscriptionError("Deepgram Flux WebSocket closed unexpectedly.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_http_response(self, connection: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in chunk:
                break
        return b"".join(chunks)


class DeepgramFluxSession:
    """One live Deepgram Flux WebSocket session."""

    def __init__(
        self,
        *,
        session_id: str,
        model: str,
        api_key: str,
        language: str,
        client_factory=FluxWebSocketClient,
        clock=time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.model = model
        self.language = language
        self._clock = clock
        self.client = client_factory(
            _flux_endpoint(model=model, language=language),
            headers={"Authorization": f"Token {api_key}"},
            timeout=REMOTE_FLUX_TIMEOUT_SECONDS,
        )
        self.client.connect()
        self.lock = threading.Lock()
        self.final_text_parts: list[str] = []
        self.partial_text = ""
        self.closed = False
        self.created_at = self._clock()
        self.updated_at = self.created_at

    def transcribe_chunk(self, audio_bytes: bytes, *, final: bool) -> dict[str, object]:
        with self.lock:
            if self.closed:
                raise SpeechValidationError("conversation stream session is already closed.", operation="transcribe_audio")
            self.client.send_binary(audio_bytes)
            if final:
                self.client.send_json({"type": "CloseStream"})
            events = self._drain_events(FLUX_FINAL_DRAIN_SECONDS if final else FLUX_DRAIN_SECONDS)
            if final:
                self.close()
            self.updated_at = self._clock()
            chunk_text = _chunk_text(events)
            text = " ".join(part for part in [*self.final_text_parts, self.partial_text] if part).strip()
            return {
                "text": text or chunk_text,
                "chunk_text": chunk_text,
                "events": [_public_event(event) for event in events],
                "turn_events": [_public_turn_event(event) for event in events if _event_type(event) in {"StartOfTurn", "EndOfTurn"}],
                "partial": not final,
                "final": final,
            }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.client.close()

    def _drain_events(self, timeout_seconds: float) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        deadline = time.monotonic() + max(0.01, timeout_seconds)
        while time.monotonic() < deadline:
            try:
                event = self.client.receive_json(max(0.01, deadline - time.monotonic()))
            except (TimeoutError, socket.timeout, queue.Empty):
                break
            if event is None:
                break
            events.append(event)
            self._apply_event(event)
        return events

    def _apply_event(self, event: dict[str, object]) -> None:
        text = _event_text(event)
        if not text:
            return
        if _event_is_final(event):
            self.final_text_parts.append(text)
            self.partial_text = ""
        else:
            self.partial_text = text


class DeepgramFluxSessionManager:
    """Own Deepgram Flux sessions for one persistent backend worker process."""

    def __init__(
        self,
        *,
        client_factory=FluxWebSocketClient,
        idle_ttl_seconds: int | None = None,
        max_age_seconds: int | None = None,
        prune_interval_seconds: int | None = None,
        max_sessions: int | None = None,
        clock=time.monotonic,
    ) -> None:
        self.client_factory = client_factory
        self.idle_ttl_seconds = max(0, idle_ttl_seconds) if idle_ttl_seconds is not None else _configured_int(
            "MAVERICK_SPEECH_FLUX_SESSION_IDLE_SECONDS",
            DEFAULT_FLUX_SESSION_IDLE_SECONDS,
            minimum=5,
        )
        self.max_age_seconds = max(1, max_age_seconds) if max_age_seconds is not None else _configured_int(
            "MAVERICK_SPEECH_FLUX_SESSION_MAX_AGE_SECONDS",
            DEFAULT_FLUX_SESSION_MAX_AGE_SECONDS,
            minimum=30,
        )
        self.prune_interval_seconds = max(0, prune_interval_seconds) if prune_interval_seconds is not None else _configured_int(
            "MAVERICK_SPEECH_FLUX_SESSION_PRUNE_INTERVAL_SECONDS",
            DEFAULT_FLUX_SESSION_PRUNE_INTERVAL_SECONDS,
            minimum=1,
        )
        self.max_sessions = max(1, max_sessions) if max_sessions is not None else _configured_int(
            "MAVERICK_SPEECH_FLUX_MAX_SESSIONS",
            DEFAULT_FLUX_MAX_SESSIONS,
            minimum=1,
        )
        self.clock = clock
        self.sessions: dict[str, DeepgramFluxSession] = {}
        self.active_session_counts: dict[str, int] = {}
        self.last_pruned_at = 0.0
        self.lock = threading.Lock()

    def transcribe_chunk(
        self,
        *,
        session_id: str,
        audio_bytes: bytes,
        final: bool,
        model: str,
        api_key: str,
        language: str,
    ) -> dict[str, object]:
        with self.lock:
            self._prune_sessions_locked(now=self.clock(), force=False)
            session = self.sessions.get(session_id)
            if session is None or session.closed:
                self._reserve_session_slot_locked()
                session = DeepgramFluxSession(
                    session_id=session_id,
                    model=model,
                    api_key=api_key,
                    language=language,
                    client_factory=self.client_factory,
                    clock=self.clock,
                )
                self.sessions[session_id] = session
            self._begin_active_session_locked(session_id)
        failed = False
        try:
            result = session.transcribe_chunk(audio_bytes, final=final)
        except Exception:
            failed = True
            with self.lock:
                if self.sessions.get(session_id) is session:
                    self.sessions.pop(session_id, None)
                self._finish_active_session_locked(session_id)
            session.close()
            raise
        finally:
            if not failed:
                with self.lock:
                    self._finish_active_session_locked(session_id)
                    if final:
                        self.sessions.pop(session_id, None)
                        session.close()
        return result

    def prune_expired_sessions(self) -> int:
        with self.lock:
            return self._prune_sessions_locked(now=self.clock(), force=True)

    def _prune_sessions_locked(self, *, now: float, force: bool) -> int:
        if not force and now - self.last_pruned_at < self.prune_interval_seconds:
            return 0
        self.last_pruned_at = now
        expired_session_ids: list[str] = []
        for session_id, session in self.sessions.items():
            if self._session_active_locked(session_id) and not session.closed:
                continue
            idle_seconds = now - session.updated_at
            age_seconds = now - session.created_at
            if session.closed or idle_seconds > self.idle_ttl_seconds or age_seconds > self.max_age_seconds:
                expired_session_ids.append(session_id)
        for session_id in expired_session_ids:
            self._close_session_locked(session_id)
        return len(expired_session_ids)

    def _reserve_session_slot_locked(self) -> None:
        while len(self.sessions) >= self.max_sessions:
            stale_session_id = self._oldest_inactive_session_id_locked()
            if stale_session_id is None:
                raise SpeechValidationError(
                    "too many active conversation stream sessions.",
                    operation="transcribe_audio",
                    allowed_values={"max_sessions": [str(self.max_sessions)]},
                )
            self._close_session_locked(stale_session_id)

    def _oldest_inactive_session_id_locked(self) -> str | None:
        inactive_sessions = [
            (session_id, session)
            for session_id, session in self.sessions.items()
            if not self._session_active_locked(session_id)
        ]
        if not inactive_sessions:
            return None
        return min(inactive_sessions, key=lambda item: item[1].updated_at)[0]

    def _close_session_locked(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        self.active_session_counts.pop(session_id, None)
        if session is not None:
            session.close()

    def _begin_active_session_locked(self, session_id: str) -> None:
        self.active_session_counts[session_id] = self.active_session_counts.get(session_id, 0) + 1

    def _finish_active_session_locked(self, session_id: str) -> None:
        count = self.active_session_counts.get(session_id, 0)
        if count <= 1:
            self.active_session_counts.pop(session_id, None)
        else:
            self.active_session_counts[session_id] = count - 1

    def _session_active_locked(self, session_id: str) -> bool:
        return self.active_session_counts.get(session_id, 0) > 0


_FLUX_MANAGER = DeepgramFluxSessionManager()


def flux_streaming_supported(settings: dict | None = None) -> bool:
    return bool(_runtime_secret(settings or {}, "deepgram_api_key")) and _persistent_backend_worker_enabled()


def transcribe_deepgram_flux_audio_chunk(
    audio_path: Path,
    *,
    settings: dict,
    language: str,
    session: dict,
) -> dict:
    api_key = _runtime_secret(settings, "deepgram_api_key")
    if not api_key:
        raise SpeechProviderUnavailableError("Deepgram API key was not delivered to Speech.")
    if not _persistent_backend_worker_enabled():
        raise SpeechProviderUnavailableError("Deepgram Flux streaming requires the persistent Speech backend worker.")
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        raise SpeechValidationError("conversation stream requires session_id.", operation="transcribe_audio")
    model = deepgram_model_for("conversation_stream", "conversation", settings=settings)
    result = _FLUX_MANAGER.transcribe_chunk(
        session_id=session_id,
        audio_bytes=audio_path.read_bytes(),
        final=bool(session.get("final")),
        model=model,
        api_key=api_key,
        language=language,
    )
    return {
        **result,
        "segments": [],
        "duration_seconds": 0.0,
        "engine": "deepgram",
        "model": model,
        "language": language,
        "language_probability": 0.0,
        "profile": "flux",
    }


def _flux_endpoint(*, model: str, language: str) -> str:
    query = [("model", model or DEEPGRAM_CONVERSATION_MODEL)]
    if language:
        query.append(("language", language))
    parsed = urlparse("wss://api.deepgram.com/v2/listen")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query), ""))


def _runtime_secret(settings: dict, logical_name: str) -> str:
    secrets = settings.get("_app_secrets") if isinstance(settings.get("_app_secrets"), dict) else {}
    value = None
    if isinstance(secrets, dict):
        value = secrets.get(logical_name)
        if value is None:
            value = secrets.get(logical_name.replace("_", "-"))
        if value is None:
            value = secrets.get(logical_name.replace("-", "_"))
    return str(value or "").strip()


def _persistent_backend_worker_enabled() -> bool:
    mode = os.environ.get("MAVERICK_SPEECH_BACKEND_WORKER", "auto").strip().lower() or "auto"
    return mode not in {"0", "false", "no", "off", "entrypoint", "process", "disabled"}


def _event_type(event: dict[str, object]) -> str:
    return str(event.get("type") or event.get("event") or "").strip()


def _event_text(event: dict[str, object]) -> str:
    transcript = str(event.get("transcript") or event.get("text") or "").strip()
    if transcript:
        return transcript
    channel = event.get("channel") if isinstance(event.get("channel"), dict) else {}
    alternatives = channel.get("alternatives") if isinstance(channel, dict) else None
    if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], dict):
        return str(alternatives[0].get("transcript") or "").strip()
    return ""


def _event_is_final(event: dict[str, object]) -> bool:
    event_type = _event_type(event)
    return event_type == "EndOfTurn" or bool(event.get("is_final") or event.get("speech_final") or event.get("final"))


def _chunk_text(events: list[dict[str, object]]) -> str:
    texts = [_event_text(event) for event in events if _event_text(event)]
    return " ".join(texts).strip()


def _public_event(event: dict[str, object]) -> dict[str, object]:
    return {
        "type": _event_type(event),
        "text": _event_text(event),
        "is_final": _event_is_final(event),
    }


def _public_turn_event(event: dict[str, object]) -> dict[str, object]:
    return {
        "type": _event_type(event),
        "text": _event_text(event),
    }


def parse_flux_url_query(url: str) -> dict[str, str]:
    """Return a compact query dict for tests and diagnostics."""
    return {key: value for key, value in parse_qsl(urlparse(url).query)}
