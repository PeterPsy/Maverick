"""Speech transcription operations."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import wave

from engines import transcribe_audio_file
from errors import SpeechProviderUnavailableError, SpeechValidationError
from models import (
    DEFAULT_INLINE_TRANSCRIPTION_PROFILE,
    MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
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


def transcribe_audio_payload(*, data_root: Path, body: dict) -> dict:
    content_type = normalized_transcription_content_type(body.get("content_type"), operation="transcribe_audio")
    language = normalized_language(body.get("language"))
    profile = normalized_transcription_profile(body.get("profile"), operation="transcribe_audio")
    body_file_path = str(body.get("_body_file_path") or "")
    if body_file_path:
        return transcribe_inline_body_file(
            data_root=data_root,
            audio_path=validated_inline_body_file_path(data_root, body_file_path),
            content_type=content_type,
            size_bytes=int(body.get("_body_file_size_bytes") or 0),
            language=language,
            profile=profile,
        )
    audio = decoded_audio(body.get("audio_base64"))
    return transcribe_bytes(
        data_root=data_root,
        audio=audio,
        content_type=content_type,
        language=language,
        profile=profile,
        source={"kind": "inline"},
    )


def transcribe_inline_body_file(
    *,
    data_root: Path,
    audio_path: Path,
    content_type: str,
    size_bytes: int,
    language: str,
    profile: str,
) -> dict:
    if not audio_path.exists() or not audio_path.is_file():
        raise SpeechValidationError("inline audio upload is unavailable.", operation="transcribe_audio")
    actual_size = audio_path.stat().st_size
    if size_bytes and size_bytes != actual_size:
        raise SpeechValidationError("inline audio upload size changed before transcription.", operation="transcribe_audio")
    validate_audio_size(actual_size, operation="transcribe_audio", max_audio_bytes=MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)
    return transcribe_path(
        data_root=data_root,
        audio_path=audio_path,
        content_type=content_type,
        size_bytes=actual_size,
        language=language,
        profile=profile,
        operation="transcribe_audio",
        source={"kind": "inline", "transport": "binary"},
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
        operation="transcribe_file",
        source={"kind": "storage", "workspace_relative_path": normalized_workspace_relative_path(body)},
    )


def transcribe_bytes(*, data_root: Path, audio: bytes, content_type: str, language: str, profile: str, source: dict) -> dict:
    extension = CONTENT_TYPE_EXTENSIONS[content_type]
    with tempfile.TemporaryDirectory(prefix="maverick-speech-stt-") as temp_dir:
        audio_path = Path(temp_dir) / f"input{extension}"
        audio_path.write_bytes(audio)
        return transcribe_path(
            data_root=data_root,
            audio_path=audio_path,
            content_type=content_type,
            size_bytes=len(audio),
            language=language,
            profile=profile,
            operation="transcribe_audio",
            source=source,
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
) -> dict:
    preflight_duration_seconds = probe_audio_duration_seconds(audio_path, content_type=content_type)
    validate_audio_duration(preflight_duration_seconds, operation=operation)
    settings = read_settings(data_root)
    if profile:
        settings = {**settings, "transcription_profile": profile}
    settings["_data_root"] = str(data_root)
    result = transcribe_audio_file(audio_path, settings=settings, language=language)
    cleaned_text = cleaned_transcript(str(result.get("text") or ""))
    duration_seconds = float(result.get("duration_seconds") or preflight_duration_seconds or 0.0)
    validate_audio_duration(duration_seconds, operation=operation)
    segments = [segment for segment in result.get("segments", []) if str(segment.get("text") or "").strip()]
    job_id = f"stt_{uuid.uuid4().hex}"
    created_at = datetime.now(tz=UTC).isoformat()
    append_job(
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
            "transcript_chars": len(cleaned_text),
            "profile": str(result.get("profile") or ""),
            "beam_size": int(result.get("beam_size") or 0),
            "worker": result.get("worker") if isinstance(result.get("worker"), dict) else {},
            "source": source,
            "retention": "metadata_only",
        },
    )
    return {
        "job_id": job_id,
        "created_at": created_at,
        "text": cleaned_text,
        "segments": segments,
        "language": str(result.get("language") or language or ""),
        "language_probability": float(result.get("language_probability") or 0.0),
        "duration_seconds": duration_seconds,
        "engine": str(result.get("engine") or ""),
        "model": str(result.get("model") or ""),
        "profile": str(result.get("profile") or ""),
        "beam_size": int(result.get("beam_size") or 0),
        "worker": result.get("worker") if isinstance(result.get("worker"), dict) else {},
        "content_type": content_type,
        "size_bytes": size_bytes,
        "retention": "metadata_only",
    }


def decoded_audio(value: object) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise SpeechValidationError(
            "Missing required field: audio_base64.",
            operation="transcribe_audio",
            expected_fields=["audio_base64", "content_type"],
        )
    try:
        audio = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise SpeechValidationError("audio_base64 must be valid base64.", operation="transcribe_audio") from error
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


def cleaned_transcript(text: str) -> str:
    transcript = " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split()).strip()
    normalized = transcript.lower().strip(" .!?")
    if normalized in HALLUCINATION_TRANSCRIPTS:
        return ""
    return transcript


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
