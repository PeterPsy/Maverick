"""Gemini Flash-Lite TTS with governed credentials and progressive PCM audio."""

from __future__ import annotations

import http.client
import io
import json
from threading import Lock
import time
from typing import Iterator
import uuid
import wave

from errors import SpeechProviderUnavailableError, SpeechValidationError
from gemini_audio import decode_audio_delta, iter_sse_events
from http_connection_pool import SpeechConnectionPool
from models import MAX_AUDIO_BYTES


GEMINI_TTS_MODEL = "gemini-3.8-flash-lite-tts"
GEMINI_TTS_HOST = "generativelanguage.googleapis.com"
GEMINI_TTS_PATH = "/v1beta/interactions"
GEMINI_TTS_SECRET = "google-ai-studio-api-key"
GEMINI_TTS_DEFAULT_VOICE = "Kore"
GEMINI_TTS_VOICES = tuple(
    {"voice_id": name, "name": name, "language": ""}
    for name in ("Kore", "Puck", "Zephyr", "Charon", "Fenrir", "Aoede")
)
_CONNECTION_POOL = SpeechConnectionPool(host=GEMINI_TTS_HOST)


def selected_gemini_voice(requested: str) -> str:
    if not requested:
        return GEMINI_TTS_DEFAULT_VOICE
    for voice in GEMINI_TTS_VOICES:
        if voice["voice_id"].lower() == requested.lower():
            return voice["voice_id"]
    raise SpeechValidationError(
        "Unsupported Gemini synthesis voice.", operation="synthesize",
        allowed_values={"voice": [voice["voice_id"] for voice in GEMINI_TTS_VOICES]},
    )


def gemini_engine_status(settings: dict) -> dict:
    delivered = settings.get("_app_secrets") or {}
    configured = bool(delivered.get(GEMINI_TTS_SECRET))
    return {
        "engine": "gemini", "label": "Gemini 3.8 Flash-Lite TTS", "kind": "tts",
        "available": configured, "configured": configured,
        "detail": "Gemini API key was delivered by Core Secrets." if configured else "Connect a Gemini API credential in Vault.",
        "model": GEMINI_TTS_MODEL, "quality_profile": "natural", "latency_profile": "remote_streaming",
        "supported_formats": ["audio/wav", "audio/pcm"],
        "voices": [dict(voice) for voice in GEMINI_TTS_VOICES],
    }


def open_gemini_stream(*, text: str, voice: str, language: str, settings: dict,
                       pool: SpeechConnectionPool | None = None) -> GeminiAudioStream:
    secrets = settings.get("_app_secrets") or {}
    api_key = str(secrets.get(GEMINI_TTS_SECRET) or "").strip()
    if not api_key:
        raise SpeechProviderUnavailableError("Gemini API key was not delivered to Speech.")
    speech_config = {"voice": selected_gemini_voice(voice)}
    if language:
        speech_config["language"] = language
    body = json.dumps({
        "model": GEMINI_TTS_MODEL,
        "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
        "generation_config": {"speech_config": [speech_config]},
        "response_format": {"type": "audio", "mime_type": "audio/l16", "sample_rate": 24000},
        "stream": True, "store": False,
    }, ensure_ascii=False).encode("utf-8")
    selected_pool = pool or _CONNECTION_POOL
    started = time.monotonic()
    connection, reused = selected_pool.acquire(timeout=45)
    try:
        connection.request("POST", GEMINI_TTS_PATH, body=body, headers={
            "x-goog-api-key": api_key, "Content-Type": "application/json", "Accept": "text/event-stream",
        })
        connect_ms = elapsed_ms(started)
        response = connection.getresponse()
        if response.status != 200:
            # Provider error bodies can echo request text or credentials.
            raise SpeechProviderUnavailableError(f"Gemini speech request failed (HTTP {response.status}).")
        if response.getheader("Content-Type", "").split(";", 1)[0].lower() != "text/event-stream":
            raise SpeechProviderUnavailableError("Gemini did not return a speech event stream.")
        return GeminiAudioStream(
            pool=selected_pool, connection=connection, response=response, started=started, reused=reused,
            timings={"upstream_connect_ms": connect_ms, "upstream_headers_ms": elapsed_ms(started)},
        )
    except (OSError, http.client.HTTPException) as error:
        selected_pool.discard(connection)
        raise SpeechProviderUnavailableError("Unable to connect to Gemini speech generation.") from error
    except Exception:
        selected_pool.discard(connection)
        raise


class GeminiAudioStream:
    def __init__(self, *, pool, connection, response, started: float, reused: bool, timings: dict) -> None:
        self._pool, self._connection, self._response = pool, connection, response
        self._started = started
        self._closed = False
        self._lock = Lock()
        self._iterated = False
        self.generation_id = f"gemini_{uuid.uuid4().hex}"
        self.connection_reused = reused
        self.timings = timings

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def iter_chunks(self) -> Iterator[bytes]:
        if self._iterated:
            raise RuntimeError("Gemini audio stream can only be consumed once.")
        self._iterated = True
        completed = False
        fully_consumed = False
        size = 0
        pending = b""
        try:
            for event in iter_sse_events(self._response, cancelled=lambda: self.closed):
                event_type = event.get("event_type")
                if event_type in {"error", "interaction.failed", "interaction.cancelled"}:
                    raise SpeechProviderUnavailableError("Gemini speech generation did not complete.")
                if event_type == "interaction.completed":
                    interaction = event.get("interaction") or {}
                    if completed or not isinstance(interaction, dict) or interaction.get("status") != "completed":
                        raise SpeechProviderUnavailableError("Gemini speech generation did not complete.")
                    completed = True
                delta = event.get("delta") or {}
                if event_type != "step.delta":
                    continue
                if not isinstance(delta, dict):
                    raise SpeechProviderUnavailableError("Gemini returned an invalid speech event.")
                if delta.get("type") != "audio":
                    continue
                if completed:
                    raise SpeechProviderUnavailableError("Gemini returned audio after speech completion.")
                audio = decode_audio_delta(delta)
                size += len(audio)
                if size > MAX_AUDIO_BYTES:
                    raise SpeechProviderUnavailableError("Gemini speech audio exceeds the response size limit.")
                if audio and "upstream_first_audio_byte_ms" not in self.timings:
                    self.timings["upstream_first_audio_byte_ms"] = elapsed_ms(self._started)
                audio = pending + audio
                aligned_size = len(audio) - len(audio) % 2
                pending = audio[aligned_size:]
                if aligned_size:
                    self.timings["upstream_last_audio_byte_ms"] = elapsed_ms(self._started)
                    yield audio[:aligned_size]
            if self.closed:
                return
            if not completed or not size or pending:
                raise SpeechProviderUnavailableError("Gemini returned incomplete speech audio.")
            fully_consumed = True
        except (OSError, ValueError, AttributeError, http.client.HTTPException) as error:
            if self.closed:
                return
            raise SpeechProviderUnavailableError("Gemini speech stream was interrupted.") from error
        finally:
            self.close(reusable=fully_consumed and not bool(getattr(self._response, "will_close", False)))

    def close(self, *, reusable: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if reusable:
                self._response.close()
                self._pool.release(self._connection)
            else:
                self._pool.discard(self._connection)
                self._response.close()


def collect_gemini_wav(*, text: str, voice: str, language: str, settings: dict) -> bytes:
    stream = open_gemini_stream(text=text, voice=voice, language=language, settings=settings)
    pcm = b"".join(stream.iter_chunks())
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)
        return output.getvalue()


def elapsed_ms(started: float) -> float:
    return round(max(0, time.monotonic() - started) * 1000, 3)
