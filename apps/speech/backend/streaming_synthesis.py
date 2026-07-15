"""Progressive Speech synthesis plans for governed backend byte streams."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Iterator
import uuid

from errors import SpeechProviderUnavailableError, SpeechValidationError
from kokoro_streaming import (
    KOKORO_PCM_CHANNELS,
    KOKORO_PCM_CONTENT_TYPE,
    KOKORO_PCM_SAMPLE_FORMAT,
    KOKORO_PCM_SAMPLE_RATE,
    open_kokoro_deepinfra_stream,
    open_kokoro_openrouter_stream,
)
from models import MAX_AUDIO_BYTES
from store import append_job, read_settings
from synthesis import (
    normalized_rate,
    normalized_text,
    normalized_voice,
    selected_kokoro_voice_id,
    selected_synthesis_language,
)


class StreamingSynthesisPlan:
    """Header metadata plus the one-shot upstream audio iterator."""

    def __init__(
        self,
        *,
        data_root: Path,
        upstream,
        job_id: str,
        created_at: str,
        text_chars: int,
        voice: str,
        language: str,
        rate: int,
        backend_entrypoint_ms: float,
        request_started: float,
        engine: str,
    ) -> None:
        self._data_root = data_root
        self._upstream = upstream
        self._job_id = job_id
        self._created_at = created_at
        self._text_chars = text_chars
        self._voice = voice
        self._language = language
        self._rate = rate
        self._engine = engine
        self._started = request_started
        timings = {
            "backend_entrypoint_ms": backend_entrypoint_ms,
            **upstream.timings,
        }
        self.stream_response = {
            "content_type": KOKORO_PCM_CONTENT_TYPE,
            "file_name": f"{job_id}.pcm",
            "cache_control": "no-store",
            "generation_id": upstream.generation_id,
            "audio": {
                "sample_rate": KOKORO_PCM_SAMPLE_RATE,
                "channels": KOKORO_PCM_CHANNELS,
                "sample_format": KOKORO_PCM_SAMPLE_FORMAT,
            },
            "timings": timings,
        }

    def iter_chunks(self) -> Iterator[bytes]:
        size_bytes = 0
        completed = False
        try:
            for chunk in self._upstream.iter_chunks():
                size_bytes += len(chunk)
                if size_bytes > MAX_AUDIO_BYTES:
                    raise SpeechProviderUnavailableError("Synthesized audio exceeds the streaming response size limit.")
                yield chunk
            completed = True
        finally:
            self._record_job(size_bytes=size_bytes, completed=completed)

    def cancel(self) -> None:
        """Close the active provider response when the downstream client leaves."""
        self._upstream.close()

    def _record_job(self, *, size_bytes: int, completed: bool) -> None:
        upstream_timings = dict(self._upstream.timings)
        request_total_seconds = max(0.0, time.monotonic() - self._started)
        job = {
            "job_id": self._job_id,
            "kind": "tts",
            "created_at": self._created_at,
            "text_chars": self._text_chars,
            "voice": self._voice,
            "rate": self._rate,
            "engine": self._engine,
            "quality_profile": "natural",
            "latency_profile": "remote_streaming",
            "content_type": KOKORO_PCM_CONTENT_TYPE,
            "size_bytes": size_bytes,
            "cache_hit": False,
            "language": self._language,
            "retention": "provider_response",
            "generation_id": self._upstream.generation_id,
            "connection_reused": bool(self._upstream.connection_reused),
            "stream_completed": completed,
            "backend_entrypoint_ms": self.stream_response["timings"]["backend_entrypoint_ms"],
            "request_total_seconds": round(request_total_seconds, 6),
        }
        for name in (
            "upstream_connect_ms",
            "upstream_headers_ms",
            "upstream_first_audio_byte_ms",
            "upstream_last_audio_byte_ms",
        ):
            if name in upstream_timings:
                job[name] = upstream_timings[name]
        append_job(self._data_root, job)


def prepare_synthesis_stream(*, data_root: Path, body: dict) -> StreamingSynthesisPlan:
    """Validate one Kokoro request and open its upstream response headers."""
    request_started = time.monotonic()
    text = normalized_text(body.get("text"))
    requested_voice = normalized_voice(body.get("voice"), default="")
    rate = normalized_rate(body.get("rate"))
    requested_format = str(body.get("format") or "pcm").strip().lower()
    if requested_format not in {"pcm", KOKORO_PCM_CONTENT_TYPE}:
        raise SpeechValidationError(
            "Progressive synthesis requires PCM output.",
            operation="synthesize",
            allowed_values={"format": ["pcm", KOKORO_PCM_CONTENT_TYPE]},
        )
    settings = read_settings(data_root)
    if isinstance(body.get("_app_secrets"), dict):
        settings = {**settings, "_app_secrets": dict(body["_app_secrets"])}
    requested_engine = str(settings.get("synthesis_engine") or "auto")
    if requested_engine not in {"kokoro-openrouter", "kokoro-deepinfra"}:
        raise SpeechProviderUnavailableError(
            "Progressive PCM synthesis requires a configured Kokoro remote engine."
        )
    language = selected_synthesis_language(settings, requested=body.get("language"), text=text)
    voice = selected_kokoro_voice_id(requested_voice, text=text, language=language)
    if requested_engine == "kokoro-deepinfra":
        upstream = open_kokoro_deepinfra_stream(
            text=text,
            voice=voice,
            language=language,
            settings=settings,
        )
    else:
        upstream = open_kokoro_openrouter_stream(text=text, voice=voice, settings=settings)
    return StreamingSynthesisPlan(
        data_root=data_root,
        upstream=upstream,
        job_id=f"tts_{uuid.uuid4().hex}",
        created_at=datetime.now(tz=UTC).isoformat(),
        text_chars=len(text),
        voice=voice,
        language=language,
        rate=rate,
        backend_entrypoint_ms=_non_negative_milliseconds(body.get("_backend_entrypoint_ms")),
        request_started=request_started,
        engine=requested_engine,
    )


def _non_negative_milliseconds(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed < 0 or parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return 0.0
    return round(parsed, 3)
