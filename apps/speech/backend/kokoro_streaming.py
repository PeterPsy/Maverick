"""Persistent low-latency OpenRouter Kokoro audio transport."""

from __future__ import annotations

import http.client
import json
from threading import Lock
import time
from typing import Callable, Iterator

from errors import SpeechProviderUnavailableError


KOKORO_OPENROUTER_HOST = "openrouter.ai"
KOKORO_OPENROUTER_PATH = "/api/v1/audio/speech"
KOKORO_OPENROUTER_MODEL = "hexgrad/kokoro-82m"
KOKORO_OPENROUTER_DEFAULT_VOICE = "af_heart"
KOKORO_PCM_CONTENT_TYPE = "audio/pcm"
KOKORO_PCM_SAMPLE_RATE = 24000
KOKORO_PCM_CHANNELS = 1
KOKORO_PCM_SAMPLE_FORMAT = "s16le"
KOKORO_STREAM_CHUNK_BYTES = 16 * 1024
REMOTE_PROVIDER_TIMEOUT_SECONDS = 45
OPENROUTER_CONNECTION_POOL_SIZE = 4


ConnectionFactory = Callable[[str, float], http.client.HTTPSConnection]


class KokoroConnectionPool:
    """Small thread-safe keep-alive pool owned by the persistent Speech worker."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory | None = None,
        max_idle: int = OPENROUTER_CONNECTION_POOL_SIZE,
    ) -> None:
        self._connection_factory = connection_factory or _https_connection
        self._max_idle = max(1, max_idle)
        self._idle: list[http.client.HTTPSConnection] = []
        self._lock = Lock()

    def acquire(self, *, timeout: float) -> tuple[http.client.HTTPSConnection, bool]:
        with self._lock:
            if self._idle:
                return self._idle.pop(), True
        return self._connection_factory(KOKORO_OPENROUTER_HOST, timeout), False

    def release(self, connection: http.client.HTTPSConnection) -> None:
        with self._lock:
            if len(self._idle) < self._max_idle:
                self._idle.append(connection)
                return
        connection.close()

    def discard(self, connection: http.client.HTTPSConnection) -> None:
        connection.close()

    def close(self) -> None:
        with self._lock:
            connections = self._idle
            self._idle = []
        for connection in connections:
            connection.close()


class KokoroOpenRouterStream:
    """One open upstream response with its first byte already available."""

    def __init__(
        self,
        *,
        pool: KokoroConnectionPool,
        connection: http.client.HTTPSConnection,
        response: http.client.HTTPResponse,
        first_chunk: bytes,
        generation_id: str,
        connection_reused: bool,
        response_format: str,
        request_started: float,
        timings: dict[str, float],
    ) -> None:
        self._pool = pool
        self._connection = connection
        self._response = response
        self._first_chunk = first_chunk
        self._request_started = request_started
        self._closed = False
        self._iterated = False
        self.generation_id = generation_id
        self.connection_reused = connection_reused
        self.response_format = response_format
        self.timings = timings

    def iter_chunks(self) -> Iterator[bytes]:
        if self._iterated:
            raise RuntimeError("Kokoro audio stream can only be consumed once.")
        self._iterated = True
        completed = False
        try:
            if self._first_chunk:
                yield self._first_chunk
                self._first_chunk = b""
            while True:
                chunk = self._response.read1(KOKORO_STREAM_CHUNK_BYTES)
                if not chunk:
                    completed = True
                    self.timings["upstream_last_audio_byte_ms"] = _elapsed_ms(self._request_started)
                    return
                yield chunk
        finally:
            self.close(reusable=completed and not bool(getattr(self._response, "will_close", False)))

    def close(self, *, reusable: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        self._response.close()
        if reusable:
            self._pool.release(self._connection)
        else:
            self._pool.discard(self._connection)


def open_kokoro_openrouter_stream(
    *,
    text: str,
    voice: str,
    settings: dict,
    response_format: str = "pcm",
    pool: KokoroConnectionPool | None = None,
) -> KokoroOpenRouterStream:
    """Open a raw OpenRouter audio stream and measure phases through first byte."""
    api_key = _runtime_secret(settings, "openrouter_api_key")
    if not api_key:
        raise SpeechProviderUnavailableError("OpenRouter API key was not delivered to Speech.")
    normalized_format = str(response_format or "pcm").strip().lower()
    if normalized_format not in {"mp3", "pcm"}:
        raise SpeechProviderUnavailableError("Kokoro OpenRouter supports only mp3 or pcm output.")
    body = json.dumps(
        {
            "model": KOKORO_OPENROUTER_MODEL,
            "input": text,
            "voice": voice or KOKORO_OPENROUTER_DEFAULT_VOICE,
            "response_format": normalized_format,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": KOKORO_PCM_CONTENT_TYPE if normalized_format == "pcm" else "audio/mpeg",
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    active_pool = pool or _OPENROUTER_CONNECTION_POOL
    request_started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(2):
        connection, reused = active_pool.acquire(timeout=REMOTE_PROVIDER_TIMEOUT_SECONDS)
        connect_ms = 0.0
        try:
            if not reused:
                connect_started = time.monotonic()
                connection.connect()
                connect_ms = _elapsed_ms(connect_started)
            connection.request("POST", KOKORO_OPENROUTER_PATH, body=body, headers=headers)
            response = connection.getresponse()
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            active_pool.discard(connection)
            last_error = error
            if reused and attempt == 0:
                continue
            break
        headers_ms = _elapsed_ms(request_started)
        if int(response.status) != 200:
            response.read(16 * 1024)
            response.close()
            active_pool.discard(connection)
            raise SpeechProviderUnavailableError(f"Kokoro OpenRouter synthesis failed with HTTP {response.status}.")
        try:
            first_chunk = response.read(1)
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            response.close()
            active_pool.discard(connection)
            raise SpeechProviderUnavailableError("Kokoro OpenRouter synthesis failed before the first audio byte.") from error
        if not first_chunk:
            response.close()
            active_pool.discard(connection)
            raise SpeechProviderUnavailableError("Kokoro OpenRouter returned an empty audio stream.")
        generation_id = _safe_generation_id(response.getheader("X-Generation-Id", ""))
        return KokoroOpenRouterStream(
            pool=active_pool,
            connection=connection,
            response=response,
            first_chunk=first_chunk,
            generation_id=generation_id,
            connection_reused=reused,
            response_format=normalized_format,
            request_started=request_started,
            timings={
                "upstream_connect_ms": round(connect_ms, 3),
                "upstream_headers_ms": round(headers_ms, 3),
                "upstream_first_audio_byte_ms": round(_elapsed_ms(request_started), 3),
            },
        )
    raise SpeechProviderUnavailableError("Kokoro OpenRouter synthesis failed.") from last_error


def collect_kokoro_openrouter_audio(*, text: str, voice: str, settings: dict, response_format: str = "mp3") -> bytes:
    stream = open_kokoro_openrouter_stream(
        text=text,
        voice=voice,
        settings=settings,
        response_format=response_format,
    )
    return b"".join(stream.iter_chunks())


def _https_connection(host: str, timeout: float) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, timeout=timeout)


def _runtime_secret(settings: dict, logical_name: str) -> str:
    secrets = settings.get("_app_secrets") if isinstance(settings.get("_app_secrets"), dict) else {}
    value = secrets.get(logical_name)
    if value is None:
        value = secrets.get(logical_name.replace("_", "-"))
    if value is None:
        value = secrets.get(logical_name.replace("-", "_"))
    return str(value or "").strip()


def _safe_generation_id(value: object) -> str:
    text = str(value or "").strip()
    if any(char in text for char in "\r\n\0"):
        return ""
    return text[:256]


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000, 3)


_OPENROUTER_CONNECTION_POOL = KokoroConnectionPool()
