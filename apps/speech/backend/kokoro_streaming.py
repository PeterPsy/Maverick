"""Persistent low-latency Kokoro audio transports."""

from __future__ import annotations

import http.client
import json
from threading import Lock
import time
from typing import Iterator

from http_connection_pool import SpeechConnectionPool

from errors import SpeechProviderUnavailableError


KOKORO_OPENROUTER_HOST = "openrouter.ai"
KOKORO_OPENROUTER_PATH = "/api/v1/audio/speech"
KOKORO_OPENROUTER_MODEL = "hexgrad/kokoro-82m"
KOKORO_OPENROUTER_DEFAULT_VOICE = "af_heart"
KOKORO_DEEPINFRA_HOST = "api.deepinfra.com"
KOKORO_DEEPINFRA_MODEL = "hexgrad/Kokoro-82M"
KOKORO_DEEPINFRA_STREAM_PATH = "/v1/text-to-speech/{voice_id}/stream"
KOKORO_PCM_CONTENT_TYPE = "audio/pcm"
KOKORO_PCM_SAMPLE_RATE = 24000
KOKORO_PCM_CHANNELS = 1
KOKORO_PCM_SAMPLE_FORMAT = "s16le"
KOKORO_STREAM_CHUNK_BYTES = 16 * 1024
REMOTE_PROVIDER_TIMEOUT_SECONDS = 45


class KokoroHttpStream:
    """One open upstream response whose body is consumed lazily."""

    def __init__(
        self,
        *,
        pool: SpeechConnectionPool,
        connection: http.client.HTTPSConnection,
        response: http.client.HTTPResponse,
        generation_id: str,
        connection_reused: bool,
        response_format: str,
        request_started: float,
        timings: dict[str, float],
        provider_name: str,
    ) -> None:
        self._pool = pool
        self._connection = connection
        self._response = response
        self._request_started = request_started
        self._closed = False
        self._close_lock = Lock()
        self._iterated = False
        self._provider_name = provider_name
        self.generation_id = generation_id
        self.connection_reused = connection_reused
        self.response_format = response_format
        self.timings = timings

    def iter_chunks(self) -> Iterator[bytes]:
        if self._iterated:
            raise RuntimeError("Kokoro audio stream can only be consumed once.")
        self._iterated = True
        completed = False
        first_audio_byte_seen = False
        try:
            while True:
                try:
                    chunk = self._response.read1(KOKORO_STREAM_CHUNK_BYTES)
                except (AttributeError, OSError, ValueError, http.client.HTTPException) as error:
                    if self.closed:
                        return
                    raise SpeechProviderUnavailableError(
                        f"Kokoro {self._provider_name} audio stream was interrupted."
                    ) from error
                if not chunk:
                    if self.closed:
                        return
                    if not first_audio_byte_seen:
                        raise SpeechProviderUnavailableError(f"Kokoro {self._provider_name} returned an empty audio stream.")
                    completed = True
                    self.timings["upstream_last_audio_byte_ms"] = _elapsed_ms(self._request_started)
                    return
                if not first_audio_byte_seen:
                    first_audio_byte_seen = True
                    self.timings["upstream_first_audio_byte_ms"] = _elapsed_ms(self._request_started)
                yield chunk
        finally:
            self.close(reusable=completed and not bool(getattr(self._response, "will_close", False)))

    def close(self, *, reusable: bool = False) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if reusable:
                self._response.close()
                self._pool.release(self._connection)
            else:
                # Close the socket first so cancellation interrupts a thread
                # currently blocked in HTTPResponse.read1().
                self._pool.discard(self._connection)
                self._response.close()

    @property
    def closed(self) -> bool:
        with self._close_lock:
            return self._closed


def open_kokoro_openrouter_stream(
    *,
    text: str,
    voice: str,
    settings: dict,
    response_format: str = "pcm",
    pool: SpeechConnectionPool | None = None,
) -> KokoroHttpStream:
    """Open a raw OpenRouter audio stream and measure its transport phases."""
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
    return _open_kokoro_http_stream(
        provider_name="OpenRouter",
        path=KOKORO_OPENROUTER_PATH,
        body=body,
        api_key=api_key,
        response_format=normalized_format,
        pool=pool or _OPENROUTER_CONNECTION_POOL,
        generation_headers=("X-Generation-Id",),
    )


def open_kokoro_deepinfra_stream(
    *,
    text: str,
    voice: str,
    language: str,
    settings: dict,
    response_format: str = "pcm",
    pool: SpeechConnectionPool | None = None,
) -> KokoroHttpStream:
    """Open DeepInfra's dedicated incremental Kokoro endpoint."""
    api_key = _runtime_secret(settings, "deepinfra_api_key")
    if not api_key:
        raise SpeechProviderUnavailableError("DeepInfra API key was not delivered to Speech.")
    normalized_format = str(response_format or "pcm").strip().lower()
    if normalized_format not in {"mp3", "pcm"}:
        raise SpeechProviderUnavailableError("Kokoro DeepInfra supports only mp3 or pcm output.")
    voice_id = _safe_voice_id(voice or KOKORO_OPENROUTER_DEFAULT_VOICE)
    body_payload = {
        "text": text,
        "model_id": KOKORO_DEEPINFRA_MODEL,
        "output_format": normalized_format,
    }
    language_code = str(language or "").strip().lower().split("-", 1)[0]
    if language_code:
        body_payload["language_code"] = language_code
    body = json.dumps(body_payload, separators=(",", ":")).encode("utf-8")
    return _open_kokoro_http_stream(
        provider_name="DeepInfra",
        path=KOKORO_DEEPINFRA_STREAM_PATH.format(voice_id=voice_id),
        body=body,
        api_key=api_key,
        response_format=normalized_format,
        pool=pool or _DEEPINFRA_CONNECTION_POOL,
        generation_headers=("X-Request-Id", "X-Generation-Id"),
    )


def _open_kokoro_http_stream(
    *,
    provider_name: str,
    path: str,
    body: bytes,
    api_key: str,
    response_format: str,
    pool: SpeechConnectionPool,
    generation_headers: tuple[str, ...],
) -> KokoroHttpStream:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": KOKORO_PCM_CONTENT_TYPE if response_format == "pcm" else "audio/mpeg",
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    request_started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(2):
        connection, reused = pool.acquire(timeout=REMOTE_PROVIDER_TIMEOUT_SECONDS)
        connect_ms = 0.0
        try:
            if not reused:
                connect_started = time.monotonic()
                connection.connect()
                connect_ms = _elapsed_ms(connect_started)
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            pool.discard(connection)
            last_error = error
            if reused and attempt == 0:
                continue
            break
        headers_ms = _elapsed_ms(request_started)
        if int(response.status) != 200:
            response.read(16 * 1024)
            response.close()
            pool.discard(connection)
            raise SpeechProviderUnavailableError(f"Kokoro {provider_name} synthesis failed with HTTP {response.status}.")
        generation_id = ""
        for header_name in generation_headers:
            generation_id = _safe_generation_id(response.getheader(header_name, ""))
            if generation_id:
                break
        return KokoroHttpStream(
            pool=pool,
            connection=connection,
            response=response,
            generation_id=generation_id,
            connection_reused=reused,
            response_format=response_format,
            request_started=request_started,
            timings={
                "upstream_connect_ms": round(connect_ms, 3),
                "upstream_headers_ms": round(headers_ms, 3),
            },
            provider_name=provider_name,
        )
    raise SpeechProviderUnavailableError(f"Kokoro {provider_name} synthesis failed.") from last_error


def collect_kokoro_openrouter_audio(*, text: str, voice: str, settings: dict, response_format: str = "mp3") -> bytes:
    stream = open_kokoro_openrouter_stream(
        text=text,
        voice=voice,
        settings=settings,
        response_format=response_format,
    )
    return b"".join(stream.iter_chunks())


def collect_kokoro_deepinfra_audio(
    *,
    text: str,
    voice: str,
    language: str,
    settings: dict,
    response_format: str = "mp3",
) -> bytes:
    stream = open_kokoro_deepinfra_stream(
        text=text,
        voice=voice,
        language=language,
        settings=settings,
        response_format=response_format,
    )
    return b"".join(stream.iter_chunks())


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


def _safe_voice_id(value: object) -> str:
    voice_id = str(value or "").strip()
    if not voice_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in voice_id):
        raise SpeechProviderUnavailableError("Kokoro DeepInfra voice id is invalid.")
    return voice_id


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000, 3)


_OPENROUTER_CONNECTION_POOL = SpeechConnectionPool(host=KOKORO_OPENROUTER_HOST)
_DEEPINFRA_CONNECTION_POOL = SpeechConnectionPool(host=KOKORO_DEEPINFRA_HOST)
