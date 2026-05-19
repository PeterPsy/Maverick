"""Speech synthesis operations."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
import uuid

from engines import resolve_local_tts_engine as resolve_local_engine
from engines import run_local_tts_engine as run_local_engine
from errors import SpeechProviderUnavailableError, SpeechValidationError
from models import DEFAULT_RATE, DEFAULT_VOICE, MAX_AUDIO_BYTES, MAX_RATE, MAX_TEXT_CHARS, MIN_RATE
from store import append_job


def synthesize_payload(*, data_root: Path, generated_storage_root: Path, body: dict) -> dict:
    text = normalized_text(body.get("text"))
    voice = normalized_voice(body.get("voice"))
    rate = normalized_rate(body.get("rate"))
    engine = resolve_local_engine()
    if engine is None:
        raise SpeechProviderUnavailableError("No local TTS engine is available for Speech synthesis.")

    audio = run_local_engine(engine, text=text, voice=voice, rate=rate)
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechValidationError(
            "Synthesized audio exceeds the response size limit.",
            allowed_values={"max_audio_bytes": [str(MAX_AUDIO_BYTES)]},
        )
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
            "content_type": "audio/wav",
            "size_bytes": len(audio),
            "retention": "ephemeral",
        },
    )
    audio_base64 = base64.b64encode(audio).decode("ascii")
    return {
        "job_id": job_id,
        "created_at": created_at,
        "content_type": "audio/wav",
        "audio_base64": audio_base64,
        "size_bytes": len(audio),
        "text_chars": len(text),
        "engine": engine.name,
        "retention": "ephemeral",
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


def normalized_voice(value: object) -> str:
    voice = str(value or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    if any(part in voice for part in ("/", "\\", "\0")):
        raise SpeechValidationError("voice must be a local engine voice id, not a path.")
    return voice[:40]


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
