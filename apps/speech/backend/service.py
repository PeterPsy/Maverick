"""Speech app service layer."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from errors import SpeechProviderUnavailableError, SpeechValidationError
from models import (
    DEFAULT_RATE,
    DEFAULT_VOICE,
    MAX_AUDIO_BYTES,
    MAX_RATE,
    MAX_TEXT_CHARS,
    MIN_RATE,
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_SYNTHESIS_ACTIONS,
)
from store import append_job, read_jobs

LOCAL_ENGINE_CANDIDATES = ("espeak", "espeak-ng")


def handle_action(data_root: Path, generated_storage_root: Path, body: dict) -> tuple[int, dict]:
    action = str(body.get("action") or "capabilities").strip()
    if action == "operations.manifest":
        return 200, operations_manifest()
    if action == "health.check":
        return 200, health_payload(data_root)
    if action == "capabilities":
        return 200, capabilities_payload()
    if action == "synthesize":
        return 200, synthesize_payload(
            data_root=data_root,
            generated_storage_root=generated_storage_root,
            body=body,
        )
    if action == "transcribe":
        return 501, {
            "error": "transcription_unavailable",
            "detail": "Speech transcription is reserved by the contract but is not implemented yet.",
        }
    return 400, {
        "error": "unsupported_action",
        "action": action,
        "detail": f"Unsupported Speech operation: {action or '<empty>'}.",
        "allowed_values": {"action": SUPPORTED_SYNTHESIS_ACTIONS + ["transcribe"]},
        "example": {"action": "capabilities"},
    }


def operations_manifest() -> dict:
    return {
        "app_id": "speech",
        "schema_version": "1",
        "operations": {
            "capabilities": {
                "description": "Report speech provider availability and supported formats.",
                "required_fields": [],
            },
            "synthesize": {
                "description": "Synthesize plain text into bounded WAV audio.",
                "required_fields": ["text"],
            },
            "health.check": {
                "description": "Report backend health and local engine availability.",
                "required_fields": [],
            },
        },
    }


def capabilities_payload() -> dict:
    engine = resolve_local_engine()
    return {
        "app_id": "speech",
        "interfaces": {
            "speech.synthesis": {
                "version": "1",
                "available": engine is not None,
                "provider_available": engine is not None,
                "engine": engine.name if engine else "",
                "content_types": SUPPORTED_CONTENT_TYPES,
                "max_text_chars": MAX_TEXT_CHARS,
                "output": {
                    "audio_base64": True,
                    "workspace_relative_path": False,
                    "absolute_paths": False,
                    "retention": "ephemeral",
                },
            },
            "speech.transcription": {
                "version": "1",
                "available": False,
                "provider_available": False,
            },
        },
    }


def health_payload(data_root: Path) -> dict:
    engine = resolve_local_engine()
    jobs = read_jobs(data_root)
    return {
        "status": "ok" if engine else "degraded",
        "provider_available": engine is not None,
        "engine": engine.name if engine else "",
        "job_count": len(jobs.get("jobs", [])),
    }


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


class LocalEngine:
    def __init__(self, *, name: str, path: str) -> None:
        self.name = name
        self.path = path


def resolve_local_engine() -> LocalEngine | None:
    for name in LOCAL_ENGINE_CANDIDATES:
        path = shutil.which(name)
        if path:
            return LocalEngine(name=name, path=path)
    return None


def run_local_engine(engine: LocalEngine, *, text: str, voice: str, rate: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="maverick-speech-") as temp_dir:
        output_path = Path(temp_dir) / "speech.wav"
        command = [engine.path, "-w", str(output_path), "-s", str(rate), "-v", voice, text]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Local TTS engine failed.").strip()
            raise SpeechProviderUnavailableError(detail)
        if not output_path.exists():
            raise SpeechProviderUnavailableError("Local TTS engine did not produce audio.")
        return output_path.read_bytes()
