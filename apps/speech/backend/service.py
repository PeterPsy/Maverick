"""Speech app service layer."""

from __future__ import annotations

from pathlib import Path

from engines import faster_whisper_worker_status, resolve_local_tts_engine as resolve_local_engine
from engines import resolve_transcription_engine
from models import (
    DEFAULT_INLINE_TRANSCRIPTION_PROFILE,
    MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
    MAX_INLINE_TRANSCRIPTION_SECONDS,
    MAX_TEXT_CHARS,
    MAX_TRANSCRIPTION_FILE_AUDIO_BYTES,
    MAX_TRANSCRIPTION_SECONDS,
    SUPPORTED_ACTIONS,
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_TRANSCRIPTION_CONTENT_TYPES,
)
from settings import combined_interface_status, engine_health_payload, get_settings_payload, list_engines_payload, set_engine_payload
from store import read_jobs, read_settings
from synthesis import synthesize_payload
from transcription import transcribe_audio_payload, transcribe_file_payload

DATA_CHANGED_ACTIONS = {"set_engine"}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "configuration"}]
    return []


def handle_action(
    data_root: Path,
    generated_storage_root: Path,
    body: dict,
    uploaded_storage_root: Path | None = None,
) -> tuple[int, dict]:
    action = str(body.get("action") or "capabilities").strip()
    if action == "operations.manifest":
        return 200, operations_manifest()
    if action == "health.check":
        return 200, health_payload(data_root)
    if action == "capabilities":
        return 200, capabilities_payload(data_root)
    if action == "list_engines":
        return 200, list_engines_payload(data_root, include_voices=include_voices_setting(body))
    if action == "engine_health":
        return 200, engine_health_payload(data_root, include_voices=include_voices_setting(body))
    if action == "get_settings":
        return 200, get_settings_payload(data_root)
    if action == "set_engine":
        return 200, set_engine_payload(data_root, body)
    if action == "worker_status":
        return 200, worker_status_payload(data_root, ensure_warm=ensure_warm_setting(body))
    if action == "prewarm_worker":
        return 200, worker_status_payload(data_root, ensure_warm=True)
    if action == "synthesize":
        return 200, synthesize_payload(
            data_root=data_root,
            generated_storage_root=generated_storage_root,
            body=body,
        )
    if action == "transcribe_audio":
        return 200, transcribe_audio_payload(data_root=data_root, body=body)
    if action == "transcribe_file":
        return 200, transcribe_file_payload(
            data_root=data_root,
            generated_storage_root=generated_storage_root,
            uploaded_storage_root=uploaded_storage_root,
            body=body,
        )
    return 400, {
        "error": "unsupported_action",
        "action": action,
        "detail": f"Unsupported Speech operation: {action or '<empty>'}.",
        "allowed_values": {"action": SUPPORTED_ACTIONS},
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
                "description": "Synthesize plain text into bounded cached WAV audio.",
                "required_fields": ["text"],
            },
            "transcribe_audio": {
                "description": "Transcribe a bounded inline audio upload.",
                "required_fields": ["content_type", "audio_base64 or HTTP binary body"],
            },
            "transcribe_file": {
                "description": "Transcribe a bounded workspace Storage audio file.",
                "required_fields": ["workspace_relative_path"],
            },
            "list_engines": {
                "description": "List local speech engines and availability.",
                "required_fields": [],
            },
            "engine_health": {
                "description": "Report synthesis and transcription engine health.",
                "required_fields": [],
            },
            "get_settings": {
                "description": "Read workspace Speech engine settings.",
                "required_fields": [],
            },
            "set_engine": {
                "description": "Update workspace Speech engine and transcription profile settings.",
                "required_fields": [],
            },
            "worker_status": {
                "description": "Report Speech persistent STT worker lifecycle status by effective transcription profile without warming models unless ensure_warm is true.",
                "required_fields": [],
            },
            "prewarm_worker": {
                "description": "Explicitly warm the Chat inline default faster-whisper worker and return worker lifecycle status.",
                "required_fields": [],
            },
            "health.check": {
                "description": "Report backend health and local engine availability.",
                "required_fields": [],
            },
        },
    }


def include_voices_setting(body: dict) -> bool:
    value = body.get("include_voices")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return True


def ensure_warm_setting(body: dict) -> bool:
    value = body.get("ensure_warm")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def capabilities_payload(data_root: Path) -> dict:
    settings = read_settings(data_root)
    engine = resolve_local_engine(settings)
    transcription_engine = resolve_transcription_engine(settings)
    inline_transcription_settings = {**settings, "transcription_profile": DEFAULT_INLINE_TRANSCRIPTION_PROFILE}
    inline_transcription_engine = resolve_transcription_engine(inline_transcription_settings)
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
                "voices": public_voice_profiles(engine) if engine else [],
                "default_voice": engine.voice_id if engine else "",
                "selected_engine": settings.get("synthesis_engine", "auto"),
                "quality_profile": engine.quality_profile if engine else "",
                "latency_profile": engine.latency_profile if engine else "",
                "cache": {"enabled": True, "scope": "workspace"},
                "output": {
                    "audio_base64": True,
                    "workspace_relative_path": False,
                    "absolute_paths": False,
                    "retention": "derived_cache",
                },
            },
            "speech.transcription": {
                "version": "1",
                "available": bool(transcription_engine),
                "provider_available": bool(transcription_engine),
                "engine": transcription_engine,
                "selected_engine": settings.get("transcription_engine", "auto"),
                "profile": settings.get("transcription_profile", "balanced"),
                "content_types": SUPPORTED_TRANSCRIPTION_CONTENT_TYPES,
                "max_audio_bytes": MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
                "max_inline_audio_bytes": MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
                "max_file_audio_bytes": MAX_TRANSCRIPTION_FILE_AUDIO_BYTES,
                "max_duration_seconds": MAX_TRANSCRIPTION_SECONDS,
                "max_inline_duration_seconds": MAX_INLINE_TRANSCRIPTION_SECONDS,
                "streaming_supported": False,
                "chunked_dictation_supported": True,
                "language_detection": "auto",
                "language_hint_supported": True,
                "profiles": ["fast", "balanced", "accurate"],
                "inline_default_profile": DEFAULT_INLINE_TRANSCRIPTION_PROFILE,
                "inline_default_profile_available": bool(inline_transcription_engine),
                "inline_default_profile_engine": inline_transcription_engine,
                "word_timestamps_supported": False,
                "inputs": {
                    "audio_base64": True,
                    "http_binary_body": True,
                    "workspace_relative_path": True,
                    "absolute_paths": False,
                },
            },
        },
    }


def public_voice_profiles(engine: object) -> list[dict]:
    profiles: list[dict] = []
    for item in getattr(engine, "voices", ()):
        if not isinstance(item, dict):
            continue
        profiles.append({key: value for key, value in item.items() if not str(key).startswith("_")})
    return profiles


def worker_status_payload(data_root: Path, *, ensure_warm: bool = False) -> dict:
    settings = read_settings(data_root)
    return {"worker_status": faster_whisper_worker_status(data_root, settings, ensure_warm=ensure_warm)}


def health_payload(data_root: Path) -> dict:
    settings = read_settings(data_root)
    engine = resolve_local_engine(settings)
    transcription_engine = resolve_transcription_engine(settings)
    jobs = read_jobs(data_root)
    synthesis_available = bool(engine)
    transcription_available = bool(transcription_engine)
    return {
        "status": combined_interface_status(synthesis_available=synthesis_available, transcription_available=transcription_available),
        "provider_available": synthesis_available or transcription_available,
        "interfaces": {
            "speech.synthesis": {"available": synthesis_available},
            "speech.transcription": {"available": transcription_available},
        },
        "synthesis_engine": engine.name if engine else "",
        "transcription_engine": transcription_engine,
        "job_count": len(jobs.get("jobs", [])),
    }
