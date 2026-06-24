"""Speech app service layer."""

from __future__ import annotations

from pathlib import Path

from engines import default_tts_voice_id, faster_whisper_worker_status, resolve_transcription_engine
from engines import synthesis_engine_statuses, transcription_engine_statuses
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
from settings import (
    SYNTHESIS_AUTO_ENGINES,
    TRANSCRIPTION_AUTO_ENGINES,
    combined_interface_status,
    engine_health_payload,
    engine_selection_summary,
    get_settings_payload,
    interface_health_summary,
    list_engines_payload,
    set_engine_payload,
    settings_with_app_secrets,
)
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
        return 200, health_payload(data_root, app_secrets=app_secrets_setting(body))
    if action == "capabilities":
        return 200, capabilities_payload(data_root, app_secrets=app_secrets_setting(body))
    if action == "list_engines":
        return 200, list_engines_payload(
            data_root,
            include_voices=include_voices_setting(body),
            app_secrets=app_secrets_setting(body),
        )
    if action == "engine_health":
        return 200, engine_health_payload(
            data_root,
            include_voices=include_voices_setting(body),
            app_secrets=app_secrets_setting(body),
        )
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


def app_secrets_setting(body: dict) -> dict | None:
    return body.get("_app_secrets") if isinstance(body.get("_app_secrets"), dict) else None


def ensure_warm_setting(body: dict) -> bool:
    value = body.get("ensure_warm")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def capabilities_payload(data_root: Path, app_secrets: dict | None = None) -> dict:
    settings = settings_with_app_secrets(data_root, app_secrets)
    synthesis_statuses = synthesis_engine_statuses(settings)
    synthesis_selection = engine_selection_summary(
        synthesis_statuses,
        requested_engine=str(settings.get("synthesis_engine") or "auto"),
        auto_candidates=SYNTHESIS_AUTO_ENGINES,
    )
    synthesis_status = status_for_effective_engine(synthesis_statuses, synthesis_selection)
    synthesis_engine = str((synthesis_status or {}).get("engine") or "")
    synthesis_available = bool(synthesis_selection["available"])
    synthesis_voices = public_voice_profiles_from_status(synthesis_status) if synthesis_available else []
    transcription_selection = engine_selection_summary(
        transcription_engine_statuses(settings),
        requested_engine=str(settings.get("transcription_engine") or "auto"),
        auto_candidates=TRANSCRIPTION_AUTO_ENGINES,
    )
    transcription_engine = str(transcription_selection["effective_engine"])
    inline_transcription_settings = {**settings, "transcription_profile": DEFAULT_INLINE_TRANSCRIPTION_PROFILE}
    inline_transcription_engine = resolve_transcription_engine(inline_transcription_settings)
    return {
        "app_id": "speech",
        "interfaces": {
            "speech.synthesis": {
                "version": "1",
                "available": synthesis_available,
                "provider_available": synthesis_available,
                "engine": synthesis_engine if synthesis_available else "",
                "content_types": SUPPORTED_CONTENT_TYPES,
                "max_text_chars": MAX_TEXT_CHARS,
                "voices": synthesis_voices,
                "default_voice": default_tts_voice_id(synthesis_engine, synthesis_voices) if synthesis_available else "",
                "selected_engine": settings.get("synthesis_engine", "auto"),
                "effective_engine": synthesis_selection["effective_engine"],
                "selected_available": synthesis_available,
                "fallback_available": synthesis_selection["fallback_available"],
                "fallback_engines": synthesis_selection["fallback_engines"],
                "quality_profile": str((synthesis_status or {}).get("quality_profile") or ""),
                "latency_profile": str((synthesis_status or {}).get("latency_profile") or ""),
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
                "effective_engine": transcription_engine,
                "selected_available": bool(transcription_selection["available"]),
                "fallback_available": transcription_selection["fallback_available"],
                "fallback_engines": transcription_selection["fallback_engines"],
                "profile": settings.get("transcription_profile", "balanced"),
                "content_types": SUPPORTED_TRANSCRIPTION_CONTENT_TYPES,
                "max_audio_bytes": MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
                "max_inline_audio_bytes": MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
                "max_file_audio_bytes": MAX_TRANSCRIPTION_FILE_AUDIO_BYTES,
                "max_duration_seconds": MAX_TRANSCRIPTION_SECONDS,
                "max_inline_duration_seconds": MAX_INLINE_TRANSCRIPTION_SECONDS,
                "streaming_supported": False,
                "chunked_dictation_supported": False,
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


def public_voice_profiles_from_status(status: dict | None) -> list[dict]:
    voices = (status or {}).get("voices")
    if not isinstance(voices, list):
        return []
    profiles: list[dict] = []
    for item in voices:
        if not isinstance(item, dict):
            continue
        profiles.append({key: value for key, value in item.items() if not str(key).startswith("_")})
    return profiles


def status_for_effective_engine(statuses: list[dict], selection: dict) -> dict | None:
    effective_engine = str(selection.get("effective_engine") or "")
    if not effective_engine:
        return None
    for status in statuses:
        if isinstance(status, dict) and status.get("engine") == effective_engine:
            return status
    return None


def worker_status_payload(data_root: Path, *, ensure_warm: bool = False) -> dict:
    settings = read_settings(data_root)
    return {"worker_status": faster_whisper_worker_status(data_root, settings, ensure_warm=ensure_warm)}


def health_payload(data_root: Path, app_secrets: dict | None = None) -> dict:
    settings = settings_with_app_secrets(data_root, app_secrets)
    synthesis_selection = engine_selection_summary(
        synthesis_engine_statuses(settings),
        requested_engine=str(settings.get("synthesis_engine") or "auto"),
        auto_candidates=SYNTHESIS_AUTO_ENGINES,
    )
    transcription_selection = engine_selection_summary(
        transcription_engine_statuses(settings),
        requested_engine=str(settings.get("transcription_engine") or "auto"),
        auto_candidates=TRANSCRIPTION_AUTO_ENGINES,
    )
    jobs = read_jobs(data_root)
    synthesis_available = bool(synthesis_selection["available"])
    transcription_available = bool(transcription_selection["available"])
    return {
        "status": combined_interface_status(synthesis_available=synthesis_available, transcription_available=transcription_available),
        "provider_available": synthesis_available or transcription_available,
        "interfaces": {
            "speech.synthesis": interface_health_summary(synthesis_selection),
            "speech.transcription": interface_health_summary(transcription_selection),
        },
        "selected": {
            "synthesis": synthesis_selection,
            "transcription": transcription_selection,
        },
        "synthesis_engine": synthesis_selection["effective_engine"],
        "transcription_engine": transcription_selection["effective_engine"],
        "job_count": len(jobs.get("jobs", [])),
    }
