"""Speech app service layer."""

from __future__ import annotations

from pathlib import Path

from engines import resolve_local_tts_engine as resolve_local_engine
from engines import resolve_transcription_engine
from models import (
    MAX_TEXT_CHARS,
    MAX_TRANSCRIPTION_AUDIO_BYTES,
    MAX_TRANSCRIPTION_SECONDS,
    SUPPORTED_ACTIONS,
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_TRANSCRIPTION_CONTENT_TYPES,
)
from settings import engine_health_payload, get_settings_payload, list_engines_payload, set_engine_payload
from store import read_jobs, read_settings
from synthesis import synthesize_payload
from transcription import transcribe_audio_payload, transcribe_file_payload


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
        return 200, list_engines_payload(data_root)
    if action == "engine_health":
        return 200, engine_health_payload(data_root)
    if action == "get_settings":
        return 200, get_settings_payload(data_root)
    if action == "set_engine":
        return 200, set_engine_payload(data_root, body)
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
                "description": "Synthesize plain text into bounded WAV audio.",
                "required_fields": ["text"],
            },
            "transcribe_audio": {
                "description": "Transcribe a bounded inline base64 audio blob.",
                "required_fields": ["audio_base64", "content_type"],
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
                "description": "Update workspace Speech engine settings.",
                "required_fields": [],
            },
            "health.check": {
                "description": "Report backend health and local engine availability.",
                "required_fields": [],
            },
        },
    }


def capabilities_payload(data_root: Path) -> dict:
    engine = resolve_local_engine()
    transcription_engine = resolve_transcription_engine(read_settings(data_root))
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
                "available": bool(transcription_engine),
                "provider_available": bool(transcription_engine),
                "engine": transcription_engine,
                "content_types": SUPPORTED_TRANSCRIPTION_CONTENT_TYPES,
                "max_audio_bytes": MAX_TRANSCRIPTION_AUDIO_BYTES,
                "max_duration_seconds": MAX_TRANSCRIPTION_SECONDS,
                "streaming_supported": False,
                "inputs": {
                    "audio_base64": True,
                    "workspace_relative_path": True,
                    "absolute_paths": False,
                },
            },
        },
    }


def health_payload(data_root: Path) -> dict:
    engine = resolve_local_engine()
    transcription_engine = resolve_transcription_engine(read_settings(data_root))
    jobs = read_jobs(data_root)
    return {
        "status": "ok" if engine or transcription_engine else "degraded",
        "provider_available": bool(engine or transcription_engine),
        "synthesis_engine": engine.name if engine else "",
        "transcription_engine": transcription_engine,
        "job_count": len(jobs.get("jobs", [])),
    }
