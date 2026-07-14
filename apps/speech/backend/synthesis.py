"""Speech synthesis operations."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid
import wave

from engines import resolve_local_tts_engine as resolve_local_engine
from engines import KOKORO_OPENROUTER_CONTENT_TYPE
from engines import KOKORO_OPENROUTER_DEFAULT_VOICE
from engines import KOKORO_OPENROUTER_LANGUAGE_DEFAULT_VOICES
from engines import KOKORO_OPENROUTER_VOICES
from engines import default_tts_voice_id
from engines import run_kokoro_openrouter
from engines import run_local_tts_engine as run_local_engine
from engines import tts_engine_cache_fingerprint
from errors import SpeechProviderUnavailableError, SpeechValidationError
from models import (
    DEFAULT_RATE,
    DEFAULT_VOICE,
    MAX_AUDIO_BYTES,
    MAX_RATE,
    MAX_TEXT_CHARS,
    MIN_RATE,
    TTS_CACHE_MAX_AGE_SECONDS,
    TTS_CACHE_MAX_BYTES,
    TTS_CACHE_CLEANUP_INTERVAL_SECONDS,
    TTS_CACHE_MAX_FILES,
)
from store import append_job, read_settings


def synthesize_payload(*, data_root: Path, generated_storage_root: Path, body: dict) -> dict:
    request_started = time.monotonic()
    text = normalized_text(body.get("text"))
    requested_voice = normalized_voice(body.get("voice"), default="")
    rate = normalized_rate(body.get("rate"))
    settings = read_settings(data_root)
    if isinstance(body.get("_app_secrets"), dict):
        settings = {**settings, "_app_secrets": dict(body["_app_secrets"])}
    requested_engine = str(settings.get("synthesis_engine") or "auto")
    language = selected_synthesis_language(settings, requested=body.get("language"), text=text)
    if requested_engine == "kokoro-openrouter":
        voice = selected_kokoro_voice_id(
            requested_voice,
            text=text,
            language=language,
        )
        output_format = normalized_output_format(
            body.get("format"),
            default=KOKORO_OPENROUTER_CONTENT_TYPE,
            formats={
                "audio/mpeg": KOKORO_OPENROUTER_CONTENT_TYPE,
                "audio/mp3": KOKORO_OPENROUTER_CONTENT_TYPE,
                "mp3": KOKORO_OPENROUTER_CONTENT_TYPE,
            },
        )
        engine_started = time.monotonic()
        audio = run_kokoro_openrouter(text=text, voice=voice, settings=settings)
        engine_seconds = time.monotonic() - engine_started
        content_type = output_format
        validate_audio_size(audio)
        job_id = f"tts_{uuid.uuid4().hex}"
        created_at = datetime.now(tz=UTC).isoformat()
        append_job(
            data_root,
            {
                "job_id": job_id,
                "kind": "tts",
                "created_at": created_at,
                "text_chars": len(text),
                "voice": voice,
                "engine": "kokoro-openrouter",
                "quality_profile": "natural",
                "latency_profile": "remote",
                "content_type": content_type,
                "size_bytes": len(audio),
                "cache_hit": False,
                "engine_seconds": round(engine_seconds, 6),
                "language": language,
                "retention": "provider_response",
            },
        )
        request_total_seconds = time.monotonic() - request_started
        return {
            "job_id": job_id,
            "created_at": created_at,
            "content_type": content_type,
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "size_bytes": len(audio),
            "text_chars": len(text),
            "engine": "kokoro-openrouter",
            "voice": voice,
            "language": language,
            "rate": rate,
            "format": output_format,
            "quality_profile": "natural",
            "latency_profile": "remote",
            "cache_hit": False,
            "metrics": {
                "engine_seconds": round(engine_seconds, 6),
                "request_total_seconds": round(request_total_seconds, 6),
            },
            "cache": {"enabled": False, "retention": "provider_response", "exportable": False},
            "retention": "provider_response",
        }
    engine = resolve_local_engine(settings)
    if engine is None:
        raise SpeechProviderUnavailableError(f"No local TTS engine is available for Speech synthesis. Requested engine: {requested_engine}.")

    output_format = normalized_output_format(
        body.get("format"),
        default="audio/wav",
        formats={"audio/wav": "audio/wav", "wav": "audio/wav"},
    )
    voice = selected_voice_id(engine, requested_voice, language=language)
    cache_fingerprint = tts_engine_cache_fingerprint(engine, voice=voice)
    cache_key = synthesis_cache_key(
        engine=engine.name,
        engine_fingerprint=cache_fingerprint,
        text=text,
        voice=voice,
        rate=rate,
        output_format=output_format,
    )
    audio = read_cached_synthesis(data_root, cache_key)
    cache_hit = audio is not None
    engine_seconds = 0.0
    if audio is None:
        engine_started = time.monotonic()
        audio = run_local_engine(engine, text=text, voice=voice or engine.voice_id or DEFAULT_VOICE, rate=rate, data_root=data_root)
        engine_seconds = time.monotonic() - engine_started
        validate_audio_size(audio)
        write_cached_synthesis(data_root, cache_key, audio)
        cache_cleaned = maybe_evict_synthesis_cache(data_root)
        if not cache_cleaned:
            enforce_synthesis_cache_size_limits(data_root)
    else:
        validate_audio_size(audio)
        maybe_evict_synthesis_cache(data_root)
    job_id = f"tts_{uuid.uuid4().hex}"
    created_at = datetime.now(tz=UTC).isoformat()
    append_job(
        data_root,
        {
            "job_id": job_id,
            "kind": "tts",
            "created_at": created_at,
            "text_chars": len(text),
            "voice": voice,
            "rate": rate,
            "engine": engine.name,
            "quality_profile": engine.quality_profile,
            "latency_profile": engine.latency_profile,
            "content_type": "audio/wav",
            "size_bytes": len(audio),
            "cache_hit": cache_hit,
            "engine_seconds": round(engine_seconds, 6),
            "language": language,
            "retention": "derived_cache",
        },
    )
    audio_base64 = base64.b64encode(audio).decode("ascii")
    request_total_seconds = time.monotonic() - request_started
    return {
        "job_id": job_id,
        "created_at": created_at,
        "content_type": "audio/wav",
        "audio_base64": audio_base64,
        "size_bytes": len(audio),
        "text_chars": len(text),
        "engine": engine.name,
        "voice": voice,
        "language": language,
        "rate": rate,
        "format": output_format,
        "quality_profile": engine.quality_profile,
        "latency_profile": engine.latency_profile,
        "cache_hit": cache_hit,
        "metrics": {
            "engine_seconds": round(engine_seconds, 6),
            "request_total_seconds": round(request_total_seconds, 6),
        },
        "cache": {"enabled": True, "retention": "derived", "exportable": False},
        "retention": "derived_cache",
    }


def normalized_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise SpeechValidationError(
            "Missing required field: text.",
            expected_fields=["text"],
            example={"action": "synthesize", "text": "Read this response aloud."},
        )
    if len(text) > MAX_TEXT_CHARS:
        raise SpeechValidationError(
            f"text must contain at most {MAX_TEXT_CHARS} characters.",
            allowed_values={"max_text_chars": [str(MAX_TEXT_CHARS)]},
        )
    return text


def normalized_voice(value: object, *, default: str = DEFAULT_VOICE) -> str:
    voice = str(value or default).strip() or default
    if any(part in voice for part in ("/", "\\", "\0")):
        raise SpeechValidationError("voice must be a local engine voice id, not a path.")
    return voice[:40]


def selected_voice_id(engine: object, requested_voice: str, *, language: str = "") -> str:
    voices = [item for item in getattr(engine, "voices", ()) if isinstance(item, dict)]
    voice_ids = [str(item.get("voice_id") or "") for item in voices]
    if requested_voice:
        requested_key = requested_voice.lower().replace("_", "-")
        for item in voices:
            voice_id = str(item.get("voice_id") or "")
            profile_language = str(item.get("language") or "").lower().replace("_", "-")
            aliases = {
                voice_id.lower().replace("_", "-"),
                profile_language,
                profile_language.split("-", 1)[0],
                str(item.get("name") or "").lower().replace("_", "-"),
            }
            if requested_key in aliases:
                return voice_id
        if voice_ids:
            raise SpeechValidationError(
                "Unsupported voice for selected synthesis engine.",
                operation="synthesize",
                allowed_values={"voice": voice_ids},
            )
        return requested_voice
    if not voices:
        return str(getattr(engine, "voice_id", "") or DEFAULT_VOICE)
    return default_tts_voice_id(str(getattr(engine, "name", "") or ""), voices, language=language)


WORD_RE = re.compile(r"[A-Za-z\u00c0-\u00ff']+")
ITALIAN_ACCENT_CHARS = frozenset("\u00e0\u00e8\u00e9\u00ec\u00f2\u00f9")
ITALIAN_TTS_MARKERS = frozenset(
    {
        "abbiamo",
        "adesso",
        "aiutarti",
        "anche",
        "certo",
        "che",
        "come",
        "con",
        "cosa",
        "corretta",
        "della",
        "delle",
        "degli",
        "del",
        "di",
        "dove",
        "fai",
        "fatto",
        "funziona",
        "grazie",
        "italiana",
        "italiano",
        "iniziale",
        "la",
        "latenza",
        "lettura",
        "messaggio",
        "modifica",
        "nel",
        "non",
        "ora",
        "parte",
        "partire",
        "parlare",
        "per",
        "perche",
        "posso",
        "pronuncia",
        "questa",
        "queste",
        "questi",
        "questo",
        "risposta",
        "sono",
        "subito",
        "tutto",
        "una",
        "usare",
        "voce",
        "vocale",
    }
)
ITALIAN_STRONG_TTS_MARKERS = frozenset(
    {
        "adesso",
        "aiutarti",
        "certo",
        "ciao",
        "fatto",
        "funziona",
        "grazie",
        "italiana",
        "italiano",
        "latenza",
        "lettura",
        "perche",
        "posso",
        "pronuncia",
        "subito",
    }
)
ENGLISH_TTS_MARKERS = frozenset(
    {
        "about",
        "and",
        "because",
        "can",
        "done",
        "for",
        "from",
        "hello",
        "message",
        "not",
        "please",
        "response",
        "speech",
        "that",
        "the",
        "this",
        "voice",
        "with",
        "you",
    }
)
ENGLISH_STRONG_TTS_MARKERS = frozenset({"hello", "please", "thanks", "this"})


def selected_kokoro_voice_id(requested_voice: str, *, text: str, language: object = "") -> str:
    if requested_voice:
        requested = requested_voice.strip()
        requested_key = requested.lower()
        for profile in KOKORO_OPENROUTER_VOICES:
            aliases = {
                str(profile.get("voice_id") or "").lower(),
                str(profile.get("language") or "").lower(),
                str(profile.get("name") or "").lower(),
            }
            if requested_key in aliases:
                return str(profile.get("voice_id") or requested)
        return requested
    language_code = normalized_language_code(language) or inferred_tts_language(text)
    return KOKORO_OPENROUTER_LANGUAGE_DEFAULT_VOICES.get(language_code, KOKORO_OPENROUTER_DEFAULT_VOICE)


def normalized_language_code(value: object) -> str:
    language = str(value or "").strip().lower().replace("_", "-")
    if not language:
        return ""
    return language.split("-", 1)[0]


def selected_synthesis_language(settings: dict, *, requested: object = "", text: str = "") -> str:
    preference = str(settings.get("synthesis_language") or "auto").strip().lower().replace("_", "-")
    if preference and preference != "auto":
        return normalized_language_code(preference)
    return normalized_language_code(requested) or inferred_tts_language(text)


def inferred_tts_language(text: str) -> str:
    normalized = text.lower()
    tokens = {token.strip("'") for token in WORD_RE.findall(normalized)}
    tokens.discard("")
    italian_score = sum(1 for token in tokens if token in ITALIAN_TTS_MARKERS)
    english_score = sum(1 for token in tokens if token in ENGLISH_TTS_MARKERS)
    if any(char in normalized for char in ITALIAN_ACCENT_CHARS):
        italian_score += 2
    if english_score == 0 and tokens.intersection(ITALIAN_STRONG_TTS_MARKERS):
        return "it"
    if italian_score == 0 and tokens.intersection(ENGLISH_STRONG_TTS_MARKERS):
        return "en"
    if italian_score >= 2 and italian_score > english_score:
        return "it"
    if english_score >= 2 and english_score > italian_score:
        return "en"
    return ""


def normalized_rate(value: object) -> int:
    if value in (None, ""):
        return DEFAULT_RATE
    try:
        rate = int(value)
    except (TypeError, ValueError) as error:
        raise SpeechValidationError("rate must be an integer.") from error
    if rate < MIN_RATE or rate > MAX_RATE:
        raise SpeechValidationError(
            f"rate must be between {MIN_RATE} and {MAX_RATE}.",
            allowed_values={"rate": [f"{MIN_RATE}-{MAX_RATE}"]},
        )
    return rate


def normalized_output_format(value: object, *, default: str, formats: dict[str, str]) -> str:
    output_format = str(value or default).strip().lower()
    if output_format in {"", "default"}:
        return default
    if output_format in formats:
        return formats[output_format]
    raise SpeechValidationError(
        "Unsupported synthesis format.",
        operation="synthesize",
        allowed_values={"format": sorted(set(formats.values()))},
    )


def synthesis_cache_key(*, engine: str, engine_fingerprint: dict, text: str, voice: str, rate: int, output_format: str) -> str:
    payload = {
        "engine": engine,
        "engine_fingerprint": engine_fingerprint,
        "format": output_format,
        "rate": rate,
        "text": text,
        "voice": voice,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def synthesis_cache_path(data_root: Path, cache_key: str) -> Path:
    return data_root / "cache" / "tts" / f"{cache_key}.wav"


def read_cached_synthesis(data_root: Path, cache_key: str) -> bytes | None:
    path = synthesis_cache_path(data_root, cache_key)
    if not path.exists() or not path.is_file():
        return None
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    if time.time() - stat.st_mtime > TTS_CACHE_MAX_AGE_SECONDS:
        path.unlink(missing_ok=True)
        return None
    if stat.st_size > MAX_AUDIO_BYTES:
        path.unlink(missing_ok=True)
        return None
    audio = path.read_bytes()
    if len(audio) > MAX_AUDIO_BYTES:
        path.unlink(missing_ok=True)
        return None
    if is_empty_wav_audio(audio):
        path.unlink(missing_ok=True)
        return None
    return audio


def write_cached_synthesis(data_root: Path, cache_key: str, audio: bytes) -> None:
    validate_audio_size(audio)
    path = synthesis_cache_path(data_root, cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(audio)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def maybe_evict_synthesis_cache(data_root: Path) -> bool:
    cache_dir = data_root / "cache" / "tts"
    if not cache_dir.exists():
        return False
    marker_path = cache_dir / ".last_cleanup"
    now = time.time()
    try:
        marker_mtime = marker_path.stat().st_mtime
    except FileNotFoundError:
        marker_mtime = 0.0
    if marker_mtime and now - marker_mtime < TTS_CACHE_CLEANUP_INTERVAL_SECONDS:
        return False
    evict_synthesis_cache(data_root)
    marker_path.touch()
    return True


def validate_audio_size(audio: bytes) -> None:
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechValidationError(
            "Synthesized audio exceeds the response size limit.",
            allowed_values={"max_audio_bytes": [str(MAX_AUDIO_BYTES)]},
        )
    if is_empty_wav_audio(audio):
        raise SpeechProviderUnavailableError("TTS engine produced empty audio.")


def is_empty_wav_audio(audio: bytes) -> bool:
    if not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        return False
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            return wav_file.getnframes() <= 0
    except (EOFError, OSError, wave.Error):
        return False


def evict_synthesis_cache(data_root: Path) -> None:
    cache_dir = data_root / "cache" / "tts"
    if not cache_dir.exists():
        return
    now = time.time()
    entries = collect_synthesis_cache_entries(cache_dir)
    bounded_entries: list[tuple[float, int, Path]] = []
    for mtime, size_bytes, path in entries:
        if size_bytes > MAX_AUDIO_BYTES or now - mtime > TTS_CACHE_MAX_AGE_SECONDS:
            _unlink_cache_file(path)
            continue
        bounded_entries.append((mtime, size_bytes, path))
    evict_synthesis_cache_entries(bounded_entries)


def enforce_synthesis_cache_size_limits(data_root: Path) -> None:
    cache_dir = data_root / "cache" / "tts"
    if not cache_dir.exists():
        return
    evict_synthesis_cache_entries(collect_synthesis_cache_entries(cache_dir))


def collect_synthesis_cache_entries(cache_dir: Path) -> list[tuple[float, int, Path]]:
    entries: list[tuple[float, int, Path]] = []
    for path in cache_dir.glob("*.wav"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
    entries.sort(key=lambda item: item[0])
    return entries


def evict_synthesis_cache_entries(entries: list[tuple[float, int, Path]]) -> None:
    total_bytes = sum(item[1] for item in entries)
    while len(entries) > TTS_CACHE_MAX_FILES or total_bytes > TTS_CACHE_MAX_BYTES:
        _, size_bytes, path = entries.pop(0)
        if _unlink_cache_file(path):
            total_bytes -= size_bytes


def _unlink_cache_file(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
