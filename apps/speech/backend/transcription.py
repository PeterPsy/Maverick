"""Speech transcription operations."""

from __future__ import annotations

import base64
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import wave

from engines import resolve_transcription_engine, transcribe_audio_file
from errors import SpeechProviderUnavailableError, SpeechValidationError
from flux_streaming import flux_streaming_supported, transcribe_deepgram_flux_audio_chunk
from models import (
    DEFAULT_INLINE_TRANSCRIPTION_PROFILE,
    MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
    MAX_INLINE_TRANSCRIPTION_SECONDS,
    MAX_TRANSCRIPTION_AUDIO_BYTES,
    MAX_TRANSCRIPTION_FILE_AUDIO_BYTES,
    MAX_TRANSCRIPTION_SECONDS,
    MIN_TRANSCRIPTION_AUDIO_BYTES,
    SUPPORTED_TRANSCRIPTION_CONTENT_TYPES,
    TRANSCRIPTION_PROFILE_MODELS,
)
from store import append_job, read_settings

HALLUCINATION_TRANSCRIPTS = {
    "bye",
    "goodbye",
    "like and subscribe",
    "please subscribe",
    "subscribe",
    "thanks for listening",
    "thanks for watching",
    "thank you",
}
COMPRESSED_AUDIO_CONTENT_TYPES = set(SUPPORTED_TRANSCRIPTION_CONTENT_TYPES) - {"audio/wav"}
CONTENT_TYPE_EXTENSIONS = {
    "audio/flac": ".flac",
    "audio/m4a": ".m4a",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}
STT_SESSION_MAX_AGE_SECONDS = 60 * 60
STT_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}$")
MAX_TRANSCRIPTION_SESSION_CHUNKS = 240
DICTATION_COMMANDS = {
    "new line": {"type": "insert_text", "text": "\n"},
    "newline": {"type": "insert_text", "text": "\n"},
    "nuova riga": {"type": "insert_text", "text": "\n"},
    "a capo": {"type": "insert_text", "text": "\n"},
    "new paragraph": {"type": "insert_text", "text": "\n\n"},
    "nuovo paragrafo": {"type": "insert_text", "text": "\n\n"},
    "delete last sentence": {"type": "delete_last_sentence"},
    "cancel last sentence": {"type": "delete_last_sentence"},
    "cancella ultima frase": {"type": "delete_last_sentence"},
    "cancella l ultima frase": {"type": "delete_last_sentence"},
}


def transcribe_audio_payload(*, data_root: Path, body: dict) -> dict:
    request_started = time.monotonic()
    upstream_body_stage_seconds = body_file_stage_seconds(body)
    body_stage_seconds = upstream_body_stage_seconds
    content_type = normalized_transcription_content_type(body.get("content_type"), operation="transcribe_audio")
    language = normalized_language(body.get("language"))
    profile = normalized_transcription_profile(body.get("profile"), operation="transcribe_audio")
    session = normalized_transcription_session(body)
    conversation_mode = conversation_mode_enabled(body)
    if conversation_mode and not session:
        raise SpeechValidationError("conversation stream requires session_id.", operation="transcribe_audio")
    dictation_mode = bool(session) or dictation_mode_enabled(body)
    close_only = close_only_stream_final_requested(session=session, dictation_mode=dictation_mode, conversation_mode=conversation_mode)
    body_file_path = str(body.get("_body_file_path") or "")
    if body_file_path:
        return transcribe_inline_body_file(
            data_root=data_root,
            audio_path=validated_inline_body_file_path(data_root, body_file_path),
            content_type=content_type,
            size_bytes=int(body.get("_body_file_size_bytes") or 0),
            language=language,
            profile=profile,
            request_started=request_started,
            body_stage_seconds=body_stage_seconds,
            upstream_body_stage_seconds=upstream_body_stage_seconds,
            allow_small_audio=close_only,
            session=session,
            dictation_mode=dictation_mode,
            app_secrets=body.get("_app_secrets") if isinstance(body.get("_app_secrets"), dict) else {},
            provider_config=body.get("_provider_config") if isinstance(body.get("_provider_config"), dict) else {},
            conversation_mode=conversation_mode,
        )
    body_decode_started = time.monotonic()
    audio = decoded_audio(body.get("audio_base64"), allow_empty=close_only)
    body_stage_seconds += time.monotonic() - body_decode_started
    return transcribe_bytes(
        data_root=data_root,
        audio=audio,
        content_type=content_type,
        language=language,
        profile=profile,
        request_started=request_started,
        body_stage_seconds=body_stage_seconds,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
        source={"kind": "inline"},
        session=session,
        dictation_mode=dictation_mode,
        app_secrets=body.get("_app_secrets") if isinstance(body.get("_app_secrets"), dict) else {},
        provider_config=body.get("_provider_config") if isinstance(body.get("_provider_config"), dict) else {},
        conversation_mode=conversation_mode,
    )


def transcribe_inline_body_file(
    *,
    data_root: Path,
    audio_path: Path,
    content_type: str,
    size_bytes: int,
    language: str,
    profile: str,
    request_started: float,
    body_stage_seconds: float,
    upstream_body_stage_seconds: float,
    allow_small_audio: bool = False,
    session: dict | None = None,
    dictation_mode: bool = False,
    app_secrets: dict | None = None,
    provider_config: dict | None = None,
    conversation_mode: bool = False,
) -> dict:
    if not audio_path.exists() or not audio_path.is_file():
        raise SpeechValidationError("inline audio upload is unavailable.", operation="transcribe_audio")
    actual_size = audio_path.stat().st_size
    if size_bytes and size_bytes != actual_size:
        raise SpeechValidationError("inline audio upload size changed before transcription.", operation="transcribe_audio")
    if not allow_small_audio:
        validate_audio_size(actual_size, operation="transcribe_audio", max_audio_bytes=MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)
    elif actual_size > MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES:
        validate_audio_size(actual_size, operation="transcribe_audio", max_audio_bytes=MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)
    return transcribe_path(
        data_root=data_root,
        audio_path=audio_path,
        content_type=content_type,
        size_bytes=actual_size,
        language=language,
        profile=profile,
        request_started=request_started,
        body_stage_seconds=body_stage_seconds,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
        operation="transcribe_audio",
        source={"kind": "inline", "transport": "binary"},
        session=session,
        dictation_mode=dictation_mode,
        app_secrets=app_secrets,
        provider_config=provider_config,
        conversation_mode=conversation_mode,
    )


def validated_inline_body_file_path(data_root: Path, value: str) -> Path:
    audio_path = Path(value).resolve()
    allowed_root = (data_root / "run" / "http-body").resolve()
    if audio_path == allowed_root or allowed_root not in audio_path.parents:
        raise SpeechValidationError("inline audio upload path is outside the Speech request body area.", operation="transcribe_audio")
    return audio_path


def transcribe_file_payload(
    *,
    data_root: Path,
    generated_storage_root: Path,
    uploaded_storage_root: Path | None,
    body: dict,
) -> dict:
    request_started = time.monotonic()
    audio_path = resolve_workspace_audio_path(
        generated_storage_root=generated_storage_root,
        uploaded_storage_root=uploaded_storage_root,
        body=body,
    )
    content_type = normalized_transcription_content_type(body.get("content_type") or content_type_from_path(audio_path), operation="transcribe_file")
    if not audio_path.exists() or not audio_path.is_file():
        raise SpeechValidationError("workspace_relative_path does not resolve to an audio file.", operation="transcribe_file")
    size_bytes = audio_path.stat().st_size
    validate_audio_size(size_bytes, operation="transcribe_file", max_audio_bytes=MAX_TRANSCRIPTION_FILE_AUDIO_BYTES)
    language = normalized_language(body.get("language"))
    return transcribe_path(
        data_root=data_root,
        audio_path=audio_path,
        content_type=content_type,
        size_bytes=size_bytes,
        language=language,
        request_started=request_started,
        body_stage_seconds=0.0,
        upstream_body_stage_seconds=0.0,
        operation="transcribe_file",
        source={"kind": "storage", "workspace_relative_path": normalized_workspace_relative_path(body)},
        app_secrets=body.get("_app_secrets") if isinstance(body.get("_app_secrets"), dict) else {},
        provider_config=body.get("_provider_config") if isinstance(body.get("_provider_config"), dict) else {},
    )


def transcribe_bytes(
    *,
    data_root: Path,
    audio: bytes,
    content_type: str,
    language: str,
    profile: str,
    request_started: float,
    body_stage_seconds: float,
    upstream_body_stage_seconds: float,
    source: dict,
    session: dict | None = None,
    dictation_mode: bool = False,
    app_secrets: dict | None = None,
    provider_config: dict | None = None,
    conversation_mode: bool = False,
) -> dict:
    extension = CONTENT_TYPE_EXTENSIONS[content_type]
    body_write_started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="maverick-speech-stt-") as temp_dir:
        audio_path = Path(temp_dir) / f"input{extension}"
        audio_path.write_bytes(audio)
        body_stage_seconds += time.monotonic() - body_write_started
        return transcribe_path(
            data_root=data_root,
            audio_path=audio_path,
            content_type=content_type,
            size_bytes=len(audio),
            language=language,
            profile=profile,
            request_started=request_started,
            body_stage_seconds=body_stage_seconds,
            upstream_body_stage_seconds=upstream_body_stage_seconds,
            operation="transcribe_audio",
            source=source,
            session=session,
            dictation_mode=dictation_mode,
            app_secrets=app_secrets,
            provider_config=provider_config,
            conversation_mode=conversation_mode,
        )


def transcribe_path(
    *,
    data_root: Path,
    audio_path: Path,
    content_type: str,
    size_bytes: int,
    language: str,
    operation: str,
    source: dict,
    profile: str = "",
    request_started: float | None = None,
    body_stage_seconds: float = 0.0,
    upstream_body_stage_seconds: float = 0.0,
    session: dict | None = None,
    dictation_mode: bool = False,
    app_secrets: dict | None = None,
    provider_config: dict | None = None,
    conversation_mode: bool = False,
) -> dict:
    if request_started is None:
        request_started = time.monotonic()
    duration_probe_seconds = 0.0
    preflight_duration_seconds = None
    settings = read_settings(data_root)
    if profile:
        settings = {**settings, "transcription_profile": profile}
    if app_secrets:
        settings = {**settings, "_app_secrets": dict(app_secrets)}
    if provider_config:
        settings = {**settings, "_provider_config": dict(provider_config)}
    settings["_data_root"] = str(data_root)
    dictation_stream_mode = deepgram_dictation_stream_enabled(
        settings,
        session=session,
        dictation_mode=dictation_mode,
        conversation_mode=conversation_mode,
    )
    close_only = close_only_stream_final_requested(
        session=session,
        dictation_mode=dictation_mode,
        conversation_mode=conversation_mode,
    )
    validate_audio_size_for_path(
        size_bytes,
        operation=operation,
        allow_small_audio=bool(close_only and dictation_stream_mode),
    )
    session_lock = (
        transcription_session_lock(data_root, str(session["session_id"]))
        if session and not conversation_mode
        else nullcontext()
    )
    with session_lock:
        session_limits = (
            validate_transcription_session_limits(data_root, session=session, chunk_size_bytes=size_bytes)
            if session and not conversation_mode
            else {}
        )
        if not conversation_mode and not dictation_stream_mode:
            duration_probe_started = time.monotonic()
            preflight_duration_seconds = probe_audio_duration_seconds(audio_path, content_type=content_type)
            duration_probe_seconds = time.monotonic() - duration_probe_started
            validate_audio_duration(preflight_duration_seconds, operation=operation)
        transcription_started = time.monotonic()
        if conversation_mode or dictation_stream_mode:
            result = transcribe_deepgram_flux_audio_chunk(audio_path, settings=settings, language=language, session=session or {})
        else:
            result = transcribe_audio_file(
                audio_path,
                settings=settings,
                language=language,
                operation=operation,
                mode="chunked_dictation" if session else "one_shot",
            )
        transcription_seconds = time.monotonic() - transcription_started
        if conversation_mode:
            return conversation_stream_response(
                data_root=data_root,
                result=result,
                transcription_seconds=transcription_seconds,
                request_started=request_started,
                body_stage_seconds=body_stage_seconds,
                upstream_body_stage_seconds=upstream_body_stage_seconds,
                duration_probe_seconds=duration_probe_seconds,
                duration_seconds=float(result.get("duration_seconds") or preflight_duration_seconds or 0.0),
                content_type=content_type,
                size_bytes=size_bytes,
                session=session or {},
                source=source,
                session_limits=session_limits,
            )
        if dictation_stream_mode:
            return dictation_stream_response(
                data_root=data_root,
                result=result,
                transcription_seconds=transcription_seconds,
                request_started=request_started,
                body_stage_seconds=body_stage_seconds,
                upstream_body_stage_seconds=upstream_body_stage_seconds,
                duration_probe_seconds=duration_probe_seconds,
                duration_seconds=float(result.get("duration_seconds") or 0.0),
                content_type=content_type,
                size_bytes=size_bytes,
                session=session or {},
                source=source,
                session_limits=session_limits,
            )
        postprocess_started = time.monotonic()
        post_processed = post_process_transcript(str(result.get("text") or ""), enable_commands=dictation_mode)
        cleaned_text = str(post_processed.get("text") or "")
        commands = [item for item in post_processed.get("commands", []) if isinstance(item, dict)]
        duration_seconds = float(result.get("duration_seconds") or preflight_duration_seconds or 0.0)
        validate_audio_duration(duration_seconds, operation=operation)
        segments = normalized_segments(result.get("segments", []), enable_commands=dictation_mode)
        session_payload = apply_transcription_session(
            data_root,
            session=session,
            chunk_text=cleaned_text,
            commands=commands,
            segments=segments,
            chunk_size_bytes=size_bytes,
            session_limits=session_limits,
        )
        postprocess_seconds = time.monotonic() - postprocess_started
        metrics = transcription_metrics(
            result=result,
            transcription_seconds=transcription_seconds,
            duration_seconds=duration_seconds,
            request_started=request_started,
            body_stage_seconds=body_stage_seconds,
            upstream_body_stage_seconds=upstream_body_stage_seconds,
            duration_probe_seconds=duration_probe_seconds,
            postprocess_seconds=postprocess_seconds,
        )
        public_text = str(session_payload.get("text") if session_payload else cleaned_text)
        job_id = f"stt_{uuid.uuid4().hex}"
        created_at = datetime.now(tz=UTC).isoformat()
        append_transcription_job(
            data_root,
            {
                "job_id": job_id,
                "kind": "stt",
                "created_at": created_at,
                "engine": str(result.get("engine") or ""),
                "model": str(result.get("model") or ""),
                "language": str(result.get("language") or language or ""),
                "content_type": content_type,
                "size_bytes": size_bytes,
                "duration_seconds": duration_seconds,
                "transcript_chars": len(public_text),
                "chunk_transcript_chars": len(cleaned_text),
                "profile": str(result.get("profile") or ""),
                "beam_size": int(result.get("beam_size") or 0),
                "worker": result.get("worker") if isinstance(result.get("worker"), dict) else {},
                "session": public_session_metadata(session_payload),
                "source": source,
                "retention": "metadata_only",
            },
            metrics=metrics,
            request_started=request_started,
            upstream_body_stage_seconds=upstream_body_stage_seconds,
        )
        return {
            "job_id": job_id,
            "created_at": created_at,
            "text": public_text,
            "chunk_text": cleaned_text,
            "commands": commands,
            "segments": segments,
            "language": str(result.get("language") or language or ""),
            "language_probability": float(result.get("language_probability") or 0.0),
            "duration_seconds": duration_seconds,
            "engine": str(result.get("engine") or ""),
            "model": str(result.get("model") or ""),
            "profile": str(result.get("profile") or ""),
            "beam_size": int(result.get("beam_size") or 0),
            "worker": result.get("worker") if isinstance(result.get("worker"), dict) else {},
            "metrics": metrics,
            **session_payload,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "retention": "metadata_only",
        }


def conversation_stream_response(
    *,
    data_root: Path,
    result: dict,
    transcription_seconds: float,
    request_started: float,
    body_stage_seconds: float,
    upstream_body_stage_seconds: float,
    duration_probe_seconds: float,
    duration_seconds: float,
    content_type: str,
    size_bytes: int,
    session: dict,
    source: dict,
    session_limits: dict,
) -> dict:
    session_id = str(session.get("session_id") or "")
    chunk_index = int(session.get("chunk_index") or 0)
    final = bool(session.get("final"))
    public_text = str(result.get("text") or "")
    chunk_text = str(result.get("chunk_text") or public_text)
    segments = normalized_segments(result.get("segments", []), enable_commands=False)
    metrics = transcription_metrics(
        result=result,
        transcription_seconds=transcription_seconds,
        duration_seconds=duration_seconds,
        request_started=request_started,
        body_stage_seconds=body_stage_seconds,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
        duration_probe_seconds=duration_probe_seconds,
        postprocess_seconds=0.0,
    )
    job_id = f"stt_{uuid.uuid4().hex}"
    created_at = datetime.now(tz=UTC).isoformat()
    append_transcription_job(
        data_root,
        {
            "job_id": job_id,
            "kind": "stt",
            "created_at": created_at,
            "engine": str(result.get("engine") or ""),
            "model": str(result.get("model") or ""),
            "language": str(result.get("language") or ""),
            "content_type": content_type,
            "size_bytes": size_bytes,
            "duration_seconds": duration_seconds,
            "transcript_chars": len(public_text),
            "chunk_transcript_chars": len(chunk_text),
            "profile": str(result.get("profile") or ""),
            "beam_size": 0,
            "worker": {},
            "session": {"session_id": session_id, "chunk_index": chunk_index, "partial": not final, "final": final},
            "source": source,
            "retention": "metadata_only",
        },
        metrics=metrics,
        request_started=request_started,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
    )
    return {
        "job_id": job_id,
        "created_at": created_at,
        "text": public_text,
        "chunk_text": chunk_text,
        "commands": [],
        "segments": segments,
        "language": str(result.get("language") or ""),
        "language_probability": float(result.get("language_probability") or 0.0),
        "duration_seconds": duration_seconds,
        "engine": str(result.get("engine") or ""),
        "model": str(result.get("model") or ""),
        "profile": str(result.get("profile") or ""),
        "beam_size": 0,
        "worker": {},
        "metrics": metrics,
        "session_id": session_id,
        "chunk_index": chunk_index,
        "partial": not final,
        "final": final,
        "events": result.get("events") if isinstance(result.get("events"), list) else [],
        "turn_events": result.get("turn_events") if isinstance(result.get("turn_events"), list) else [],
        "content_type": content_type,
        "size_bytes": size_bytes,
        "retention": "metadata_only",
    }


def dictation_stream_response(
    *,
    data_root: Path,
    result: dict,
    transcription_seconds: float,
    request_started: float,
    body_stage_seconds: float,
    upstream_body_stage_seconds: float,
    duration_probe_seconds: float,
    duration_seconds: float,
    content_type: str,
    size_bytes: int,
    session: dict,
    source: dict,
    session_limits: dict,
) -> dict:
    session_id = str(session.get("session_id") or "")
    chunk_index = int(session.get("chunk_index") or 0)
    final = bool(session.get("final"))
    existing_state = read_transcription_session(data_root, session_id)
    existing_text = str(existing_state.get("text") or "")
    stable_chunk_text = finalized_flux_dictation_chunk_text(result, existing_text=existing_text, final=final)
    postprocess_started = time.monotonic()
    post_processed = post_process_transcript(stable_chunk_text, enable_commands=True)
    cleaned_text = str(post_processed.get("text") or "")
    commands = [item for item in post_processed.get("commands", []) if isinstance(item, dict)]
    segments: list[dict] = []
    session_payload = apply_transcription_session(
        data_root,
        session=session,
        chunk_text=cleaned_text,
        commands=commands,
        segments=segments,
        chunk_size_bytes=size_bytes,
        session_limits=session_limits,
    )
    postprocess_seconds = time.monotonic() - postprocess_started
    public_text = str(session_payload.get("text") or "")
    metrics = transcription_metrics(
        result=result,
        transcription_seconds=transcription_seconds,
        duration_seconds=duration_seconds,
        request_started=request_started,
        body_stage_seconds=body_stage_seconds,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
        duration_probe_seconds=duration_probe_seconds,
        postprocess_seconds=postprocess_seconds,
    )
    job_id = f"stt_{uuid.uuid4().hex}"
    created_at = datetime.now(tz=UTC).isoformat()
    append_transcription_job(
        data_root,
        {
            "job_id": job_id,
            "kind": "stt",
            "created_at": created_at,
            "engine": str(result.get("engine") or ""),
            "model": str(result.get("model") or ""),
            "language": str(result.get("language") or ""),
            "content_type": content_type,
            "size_bytes": size_bytes,
            "duration_seconds": duration_seconds,
            "transcript_chars": len(public_text),
            "chunk_transcript_chars": len(cleaned_text),
            "profile": str(result.get("profile") or ""),
            "beam_size": 0,
            "worker": {},
            "session": public_session_metadata(session_payload),
            "source": source,
            "retention": "metadata_only",
        },
        metrics=metrics,
        request_started=request_started,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
    )
    return {
        "job_id": job_id,
        "created_at": created_at,
        "text": public_text,
        "chunk_text": cleaned_text,
        "commands": commands,
        "segments": segments,
        "language": str(result.get("language") or ""),
        "language_probability": float(result.get("language_probability") or 0.0),
        "duration_seconds": duration_seconds,
        "engine": str(result.get("engine") or ""),
        "model": str(result.get("model") or ""),
        "profile": str(result.get("profile") or ""),
        "beam_size": 0,
        "worker": {},
        "metrics": metrics,
        **session_payload,
        "events": result.get("events") if isinstance(result.get("events"), list) else [],
        "turn_events": result.get("turn_events") if isinstance(result.get("turn_events"), list) else [],
        "content_type": content_type,
        "size_bytes": size_bytes,
        "retention": "metadata_only",
    }


def normalized_segments(value: object, *, enable_commands: bool = False) -> list[dict]:
    segments: list[dict] = []
    if not isinstance(value, list):
        return segments
    for segment in value:
        if not isinstance(segment, dict):
            continue
        text = cleaned_transcript(str(segment.get("text") or ""), enable_commands=enable_commands)
        if not text.strip():
            continue
        segments.append(
            {
                "start": float(segment.get("start") or 0.0),
                "end": float(segment.get("end") or 0.0),
                "text": text,
            }
        )
    return segments


def transcription_metrics(
    *,
    result: dict,
    transcription_seconds: float,
    duration_seconds: float,
    request_started: float,
    body_stage_seconds: float,
    upstream_body_stage_seconds: float,
    duration_probe_seconds: float,
    postprocess_seconds: float,
) -> dict:
    worker = result.get("worker") if isinstance(result.get("worker"), dict) else {}
    model_load_seconds = float(worker.get("model_load_seconds") or worker.get("startup_model_load_seconds") or 0.0)
    realtime_factor = transcription_seconds / duration_seconds if duration_seconds > 0 else 0.0
    request_total_seconds = time.monotonic() - request_started + upstream_body_stage_seconds
    return {
        "request_total_seconds": rounded_seconds(request_total_seconds),
        "body_stage_seconds": rounded_seconds(body_stage_seconds),
        "duration_probe_seconds": rounded_seconds(duration_probe_seconds),
        "engine_seconds": rounded_seconds(transcription_seconds),
        "transcription_seconds": rounded_seconds(transcription_seconds),
        "postprocess_seconds": rounded_seconds(postprocess_seconds),
        "store_seconds": 0.0,
        "audio_duration_seconds": round(max(0.0, duration_seconds), 6),
        "realtime_factor": round(max(0.0, realtime_factor), 6),
        "cold_start": bool(worker.get("cold_start")),
        "model_load_seconds": rounded_seconds(model_load_seconds),
    }


def finish_transcription_metrics(
    metrics: dict,
    *,
    request_started: float,
    upstream_body_stage_seconds: float,
    store_started: float,
) -> None:
    metrics["store_seconds"] = rounded_seconds(time.monotonic() - store_started)
    metrics["request_total_seconds"] = rounded_seconds(time.monotonic() - request_started + upstream_body_stage_seconds)


def append_transcription_job(
    data_root: Path,
    job: dict,
    *,
    metrics: dict,
    request_started: float,
    upstream_body_stage_seconds: float,
) -> None:
    job["metrics"] = persisted_transcription_metrics(metrics)
    store_started = time.monotonic()
    append_job(data_root, job)
    finish_transcription_metrics(
        metrics,
        request_started=request_started,
        upstream_body_stage_seconds=upstream_body_stage_seconds,
        store_started=store_started,
    )


def persisted_transcription_metrics(metrics: dict) -> dict:
    omitted = {"request_total_seconds", "store_seconds"}
    return {key: value for key, value in metrics.items() if key not in omitted}


def rounded_seconds(value: float) -> float:
    return round(max(0.0, float(value or 0.0)), 6)


def body_file_stage_seconds(body: dict) -> float:
    return rounded_seconds(body.get("_body_file_stage_seconds") or 0.0)


def close_only_stream_final_requested(
    *,
    session: dict | None,
    dictation_mode: bool,
    conversation_mode: bool,
) -> bool:
    return bool(session and session.get("final") and (dictation_mode or conversation_mode))


def validate_audio_size_for_path(size_bytes: int, *, operation: str, allow_small_audio: bool = False) -> None:
    max_audio_bytes = MAX_TRANSCRIPTION_FILE_AUDIO_BYTES if operation == "transcribe_file" else MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES
    if allow_small_audio and size_bytes < MIN_TRANSCRIPTION_AUDIO_BYTES:
        return
    validate_audio_size(size_bytes, operation=operation, max_audio_bytes=max_audio_bytes)


@contextmanager
def transcription_session_lock(data_root: Path, session_id: str):
    lock_path = data_root / "run" / "stt-sessions" / "locks" / f"{session_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass


def validate_transcription_session_limits(data_root: Path, *, session: dict, chunk_size_bytes: int) -> dict:
    cleanup_transcription_sessions(data_root)
    session_id = str(session["session_id"])
    chunk_index = int(session.get("chunk_index") or 0)
    state = read_transcription_session(data_root, session_id)
    now = time.time()
    created_at = session_created_at(state, now=now)
    previous_total_size = int(state.get("total_size_bytes") or legacy_session_total_size_bytes(state))
    total_size_bytes = previous_total_size + max(0, chunk_size_bytes)
    previous_chunk_count = int(state.get("chunk_count") or legacy_session_chunk_count(state))
    chunk_count = previous_chunk_count + (1 if chunk_size_bytes > 0 else 0)
    if chunk_index != previous_chunk_count:
        raise SpeechValidationError(
            f"dictation session chunk_index must be {previous_chunk_count}.",
            operation="transcribe_audio",
            allowed_values={"expected_chunk_index": [str(previous_chunk_count)]},
        )
    if total_size_bytes > MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES:
        raise SpeechValidationError(
            f"dictation session audio must be at most {MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES} bytes.",
            operation="transcribe_audio",
            allowed_values={"max_audio_bytes": [str(MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)]},
        )
    if now - created_at > MAX_INLINE_TRANSCRIPTION_SECONDS:
        raise SpeechValidationError(
            f"dictation session must finish within {MAX_INLINE_TRANSCRIPTION_SECONDS} seconds.",
            operation="transcribe_audio",
            allowed_values={"max_duration_seconds": [str(MAX_INLINE_TRANSCRIPTION_SECONDS)]},
        )
    if chunk_count > MAX_TRANSCRIPTION_SESSION_CHUNKS:
        raise SpeechValidationError(
            f"dictation session must contain at most {MAX_TRANSCRIPTION_SESSION_CHUNKS} chunks.",
            operation="transcribe_audio",
            allowed_values={"max_session_chunks": [str(MAX_TRANSCRIPTION_SESSION_CHUNKS)]},
        )
    return {
        "created_at": created_at,
        "updated_at": now,
        "total_size_bytes": total_size_bytes,
        "chunk_count": chunk_count,
    }


def session_created_at(state: dict, *, now: float) -> float:
    try:
        created_at = float(state.get("created_at") or 0.0)
    except (TypeError, ValueError):
        created_at = 0.0
    return created_at if created_at > 0 else now


def legacy_session_total_size_bytes(state: dict) -> int:
    chunks = state.get("chunks") if isinstance(state.get("chunks"), list) else []
    total = 0
    for chunk in chunks:
        if isinstance(chunk, dict):
            total += max(0, int(chunk.get("size_bytes") or 0))
    return total


def legacy_session_chunk_count(state: dict) -> int:
    chunks = state.get("chunks") if isinstance(state.get("chunks"), list) else []
    return len(chunks)


def deepgram_dictation_stream_enabled(
    settings: dict,
    *,
    session: dict | None,
    dictation_mode: bool,
    conversation_mode: bool,
) -> bool:
    if conversation_mode or not session or not dictation_mode:
        return False
    return resolve_transcription_engine(settings) == "deepgram" and flux_streaming_supported(settings)


def finalized_flux_dictation_chunk_text(result: dict, *, existing_text: str, final: bool) -> str:
    events = result.get("events") if isinstance(result.get("events"), list) else []
    finalized_texts = [
        str(event.get("text") or "").strip()
        for event in events
        if isinstance(event, dict) and bool(event.get("is_final")) and str(event.get("text") or "").strip()
    ]
    if finalized_texts:
        return incremental_transcript_text(existing_text, " ".join(finalized_texts).strip())
    if final:
        return incremental_transcript_text(existing_text, str(result.get("text") or ""))
    return ""


def incremental_transcript_text(existing_text: str, full_text: str) -> str:
    existing = normalized_transcript_text(existing_text)
    full = normalized_transcript_text(full_text)
    if not full or full == existing:
        return ""
    if existing and full.startswith(existing):
        return full[len(existing) :].strip()
    return full


def public_session_metadata(session_payload: dict) -> dict:
    return {
        key: session_payload[key]
        for key in ("session_id", "chunk_index", "partial", "final")
        if key in session_payload
    }


def decoded_audio(value: object, *, allow_empty: bool = False) -> bytes:
    if not isinstance(value, str) or not value.strip():
        if allow_empty:
            return b""
        raise SpeechValidationError(
            "Missing required field: audio_base64.",
            operation="transcribe_audio",
            expected_fields=["audio_base64", "content_type"],
        )
    try:
        audio = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise SpeechValidationError("audio_base64 must be valid base64.", operation="transcribe_audio") from error
    if allow_empty and len(audio) < MIN_TRANSCRIPTION_AUDIO_BYTES:
        return audio
    validate_audio_size(len(audio), operation="transcribe_audio", max_audio_bytes=MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)
    return audio


def validate_audio_size(size_bytes: int, *, operation: str, max_audio_bytes: int = MAX_TRANSCRIPTION_AUDIO_BYTES) -> None:
    if size_bytes < MIN_TRANSCRIPTION_AUDIO_BYTES:
        raise SpeechValidationError(
            "audio is too small to transcribe.",
            operation=operation,
            allowed_values={"min_audio_bytes": [str(MIN_TRANSCRIPTION_AUDIO_BYTES)]},
        )
    if size_bytes > max_audio_bytes:
        raise SpeechValidationError(
            f"audio must be at most {max_audio_bytes} bytes.",
            operation=operation,
            allowed_values={"max_audio_bytes": [str(max_audio_bytes)]},
        )


def validate_audio_duration(duration_seconds: float | None, *, operation: str) -> None:
    if duration_seconds is None:
        return
    if duration_seconds > MAX_TRANSCRIPTION_SECONDS:
        raise SpeechValidationError(
            f"audio must be at most {MAX_TRANSCRIPTION_SECONDS} seconds.",
            operation=operation,
            allowed_values={"max_duration_seconds": [str(MAX_TRANSCRIPTION_SECONDS)]},
        )


def probe_audio_duration_seconds(audio_path: Path, *, content_type: str = "") -> float | None:
    wav_duration = probe_wav_duration_seconds(audio_path)
    if wav_duration is not None:
        return wav_duration
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        if content_type in COMPRESSED_AUDIO_CONTENT_TYPES:
            raise SpeechProviderUnavailableError("ffprobe is required to validate compressed audio duration before transcription.")
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        duration = float((result.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration >= 0 else None


def probe_wav_duration_seconds(audio_path: Path) -> float | None:
    try:
        with wave.open(str(audio_path), "rb") as audio:
            frame_rate = audio.getframerate()
            if frame_rate <= 0:
                return None
            return audio.getnframes() / float(frame_rate)
    except (OSError, EOFError, wave.Error):
        return None


def normalized_transcription_content_type(value: object, *, operation: str) -> str:
    content_type = str(value or "").split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_TRANSCRIPTION_CONTENT_TYPES:
        raise SpeechValidationError(
            "Unsupported audio content_type.",
            operation=operation,
            allowed_values={"content_type": SUPPORTED_TRANSCRIPTION_CONTENT_TYPES},
        )
    return content_type


def normalized_language(value: object) -> str:
    language = str(value or "").strip().lower().replace("_", "-")
    if not language:
        return ""
    if len(language) > 35 or any(part in language for part in ("/", "\\", "\0", " ")):
        raise SpeechValidationError("language must be a short language code.", operation="transcribe_audio")
    primary_subtag = language.split("-", 1)[0]
    if not primary_subtag.isalpha() or len(primary_subtag) < 2 or len(primary_subtag) > 3:
        raise SpeechValidationError("language must start with an ISO language code.", operation="transcribe_audio")
    return primary_subtag


def normalized_transcription_profile(value: object, *, operation: str) -> str:
    profile = str(value or "").strip().lower()
    if not profile:
        return DEFAULT_INLINE_TRANSCRIPTION_PROFILE
    if profile not in TRANSCRIPTION_PROFILE_MODELS:
        raise SpeechValidationError(
            "Unsupported transcription profile.",
            operation=operation,
            allowed_values={"profile": sorted(TRANSCRIPTION_PROFILE_MODELS)},
        )
    return profile


def normalized_transcription_session(body: dict) -> dict | None:
    session_id = str(body.get("session_id") or body.get("dictation_session_id") or "").strip()
    if not session_id:
        return None
    if not STT_SESSION_ID_PATTERN.match(session_id):
        raise SpeechValidationError("session_id must be a short dictation session identifier.", operation="transcribe_audio")
    try:
        chunk_index = int(body.get("chunk_index") or 0)
    except (TypeError, ValueError) as error:
        raise SpeechValidationError("chunk_index must be an integer.", operation="transcribe_audio") from error
    if chunk_index < 0:
        raise SpeechValidationError("chunk_index must not be negative.", operation="transcribe_audio")
    return {
        "session_id": session_id,
        "chunk_index": chunk_index,
        "final": truthy(body.get("final", body.get("is_final", False))),
    }


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "final"}


def conversation_mode_enabled(body: dict) -> bool:
    return truthy(body.get("conversation", body.get("conversation_mode", False)))


def dictation_mode_enabled(body: dict) -> bool:
    if "dictation" in body:
        return truthy(body.get("dictation"))
    return truthy(body.get("dictation_mode"))


def cleaned_transcript(text: str, *, enable_commands: bool = False) -> str:
    return str(post_process_transcript(text, enable_commands=enable_commands).get("text") or "")


def post_process_transcript(text: str, *, enable_commands: bool = False) -> dict:
    transcript = normalized_transcript_text(text)
    normalized = transcript.lower().strip(" .!?")
    if normalized in HALLUCINATION_TRANSCRIPTS:
        return {"text": "", "commands": []}
    command = dictation_command(transcript) if enable_commands else {}
    if command:
        return {"text": str(command.get("text") or ""), "commands": [command]}
    transcript = remove_adjacent_repeated_words(clean_punctuation_spacing(transcript))
    return {"text": transcript, "commands": []}


def normalized_transcript_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split()).strip()


def dictation_command(text: str) -> dict:
    key = re.sub(r"['’]", " ", text.lower())
    key = re.sub(r"[^a-zàèéìòù0-9 ]+", " ", key)
    key = " ".join(key.split())
    command = DICTATION_COMMANDS.get(key)
    return dict(command) if command else {}


def clean_punctuation_spacing(text: str) -> str:
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", text)
    cleaned = re.sub(r"([,;:!?])(?=\S)", r"\1 ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def remove_adjacent_repeated_words(text: str) -> str:
    words = text.split()
    if len(words) < 2:
        return text
    result: list[str] = []
    previous_normalized = ""
    repeat_count = 0
    for word in words:
        normalized = word.strip(".,;:!?").lower()
        if normalized and normalized == previous_normalized:
            repeat_count += 1
            if len(normalized) > 2 or repeat_count > 1:
                trailing_punctuation = re.search(r"([,.;:!?]+)$", word)
                if trailing_punctuation and result and not result[-1].endswith(tuple(",.;:!?")):
                    result[-1] = f"{result[-1]}{trailing_punctuation.group(1)}"
                continue
        else:
            previous_normalized = normalized
            repeat_count = 0
        result.append(word)
    return " ".join(result).strip()


def apply_transcription_session(
    data_root: Path,
    *,
    session: dict | None,
    chunk_text: str,
    commands: list[dict],
    segments: list[dict],
    chunk_size_bytes: int = 0,
    session_limits: dict | None = None,
) -> dict:
    if not session:
        return {}
    cleanup_transcription_sessions(data_root)
    session_id = str(session["session_id"])
    chunk_index = int(session["chunk_index"])
    final = bool(session["final"])
    state = read_transcription_session(data_root, session_id)
    now = time.time()
    limits = session_limits if isinstance(session_limits, dict) else {}
    created_at = float(limits.get("created_at") or state.get("created_at") or now)
    total_size_bytes = int(limits.get("total_size_bytes") or (int(state.get("total_size_bytes") or 0) + max(0, chunk_size_bytes)))
    chunk_count = int(limits.get("chunk_count") or (int(state.get("chunk_count") or len(state.get("chunks") or [])) + (1 if chunk_size_bytes > 0 else 0)))
    text = str(state.get("text") or "")
    if any(command.get("type") == "delete_last_sentence" for command in commands):
        text = delete_last_sentence(text)
    elif chunk_text:
        text = append_dictation_text(text, chunk_text)
    chunks = state.get("chunks") if isinstance(state.get("chunks"), list) else []
    chunks.append({"chunk_index": chunk_index, "text_chars": len(chunk_text), "segments": len(segments), "size_bytes": max(0, chunk_size_bytes)})
    state = {
        "schema_version": "1",
        "session_id": session_id,
        "created_at": created_at,
        "updated_at": now,
        "text": text,
        "total_size_bytes": total_size_bytes,
        "chunk_count": chunk_count,
        "chunks": chunks[-MAX_TRANSCRIPTION_SESSION_CHUNKS:],
    }
    if final:
        remove_transcription_session(data_root, session_id)
    else:
        write_transcription_session(data_root, session_id, state)
    return {
        "session_id": session_id,
        "chunk_index": chunk_index,
        "partial": not final,
        "final": final,
        "text": text,
        "chunk_text": chunk_text,
    }


def append_dictation_text(existing: str, insertion: str) -> str:
    if not insertion:
        return existing
    if not existing:
        return insertion
    if insertion.startswith("\n") or existing.endswith(("\n", " ", "\t")):
        return f"{existing}{insertion}"
    if insertion[:1] in {".", ",", ";", ":", "!", "?"}:
        return f"{existing}{insertion}"
    return f"{existing} {insertion}"


def delete_last_sentence(text: str) -> str:
    stripped = text.rstrip()
    if not stripped:
        return ""
    search_end = len(stripped) - 1
    if stripped[search_end] in ".!?":
        search_end -= 1
    for index in range(search_end, -1, -1):
        if stripped[index] in ".!?\n":
            return stripped[: index + 1].rstrip()
    return ""


def transcription_session_path(data_root: Path, session_id: str) -> Path:
    return data_root / "run" / "stt-sessions" / f"{session_id}.json"


def read_transcription_session(data_root: Path, session_id: str) -> dict:
    path = transcription_session_path(data_root, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema_version": "1", "session_id": session_id, "text": "", "chunks": []}
    return payload if isinstance(payload, dict) else {"schema_version": "1", "session_id": session_id, "text": "", "chunks": []}


def write_transcription_session(data_root: Path, session_id: str, payload: dict) -> None:
    path = transcription_session_path(data_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def remove_transcription_session(data_root: Path, session_id: str) -> None:
    try:
        transcription_session_path(data_root, session_id).unlink()
    except FileNotFoundError:
        pass


def cleanup_transcription_sessions(data_root: Path) -> None:
    session_dir = data_root / "run" / "stt-sessions"
    if not session_dir.exists():
        return
    now = time.time()
    for path in session_dir.glob("*.json"):
        try:
            if now - path.stat().st_mtime > STT_SESSION_MAX_AGE_SECONDS:
                path.unlink()
        except FileNotFoundError:
            continue


def resolve_workspace_audio_path(
    *,
    generated_storage_root: Path,
    uploaded_storage_root: Path | None,
    body: dict,
) -> Path:
    workspace_relative_path = normalized_workspace_relative_path(body)
    roots = {
        "storage/generated/": generated_storage_root,
        "storage/uploaded/": uploaded_storage_root,
    }
    for prefix, root in roots.items():
        if root is not None and workspace_relative_path.startswith(prefix):
            relative = workspace_relative_path.removeprefix(prefix)
            return safe_child_path(root, relative)
    raise SpeechValidationError(
        "workspace_relative_path must be under storage/uploaded/ or storage/generated/.",
        operation="transcribe_file",
        expected_fields=["workspace_relative_path"],
    )


def normalized_workspace_relative_path(body: dict) -> str:
    return str(body.get("workspace_relative_path") or "").strip().replace("\\", "/").lstrip("/")


def safe_child_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise SpeechValidationError("Audio path escapes the workspace storage root.", operation="transcribe_file")
    return candidate


def content_type_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".flac": "audio/flac",
        ".m4a": "audio/m4a",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
    }.get(suffix, "")
