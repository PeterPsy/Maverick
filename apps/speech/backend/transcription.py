"""Speech transcription operations."""

from __future__ import annotations

import base64
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
STT_SESSION_MAX_AGE_SECONDS = 60 * 60
STT_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}$")
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
    content_type = normalized_transcription_content_type(body.get("content_type"), operation="transcribe_audio")
    language = normalized_language(body.get("language"))
    profile = normalized_transcription_profile(body.get("profile"), operation="transcribe_audio")
    session = normalized_transcription_session(body)
    dictation_mode = bool(session) or dictation_mode_enabled(body)
    body_file_path = str(body.get("_body_file_path") or "")
    if body_file_path:
        return transcribe_inline_body_file(
            data_root=data_root,
            audio_path=validated_inline_body_file_path(data_root, body_file_path),
            content_type=content_type,
            size_bytes=int(body.get("_body_file_size_bytes") or 0),
            language=language,
            profile=profile,
            session=session,
            dictation_mode=dictation_mode,
        )
    audio = decoded_audio(body.get("audio_base64"))
    return transcribe_bytes(
        data_root=data_root,
        audio=audio,
        content_type=content_type,
        language=language,
        profile=profile,
        source={"kind": "inline"},
        session=session,
        dictation_mode=dictation_mode,
    )


def transcribe_inline_body_file(
    *,
    data_root: Path,
    audio_path: Path,
    content_type: str,
    size_bytes: int,
    language: str,
    profile: str,
    session: dict | None = None,
    dictation_mode: bool = False,
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
        session=session,
        dictation_mode=dictation_mode,
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
    dictation_mode = dictation_mode_enabled(body)
    return transcribe_path(
        data_root=data_root,
        audio_path=audio_path,
        content_type=content_type,
        size_bytes=size_bytes,
        language=language,
        operation="transcribe_file",
        source={"kind": "storage", "workspace_relative_path": normalized_workspace_relative_path(body)},
        dictation_mode=dictation_mode,
    )


def transcribe_bytes(
    *,
    data_root: Path,
    audio: bytes,
    content_type: str,
    language: str,
    profile: str,
    source: dict,
    session: dict | None = None,
    dictation_mode: bool = False,
) -> dict:
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
            session=session,
            dictation_mode=dictation_mode,
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
    session: dict | None = None,
    dictation_mode: bool = False,
) -> dict:
    preflight_duration_seconds = probe_audio_duration_seconds(audio_path, content_type=content_type)
    validate_audio_duration(preflight_duration_seconds, operation=operation)
    settings = read_settings(data_root)
    if profile:
        settings = {**settings, "transcription_profile": profile}
    settings["_data_root"] = str(data_root)
    transcription_started = time.monotonic()
    result = transcribe_audio_file(audio_path, settings=settings, language=language)
    transcription_seconds = time.monotonic() - transcription_started
    post_processed = post_process_transcript(str(result.get("text") or ""), enable_commands=dictation_mode)
    cleaned_text = str(post_processed.get("text") or "")
    commands = [item for item in post_processed.get("commands", []) if isinstance(item, dict)]
    duration_seconds = float(result.get("duration_seconds") or preflight_duration_seconds or 0.0)
    validate_audio_duration(duration_seconds, operation=operation)
    segments = normalized_segments(result.get("segments", []), enable_commands=dictation_mode)
    metrics = transcription_metrics(result=result, transcription_seconds=transcription_seconds, duration_seconds=duration_seconds)
    session_payload = apply_transcription_session(
        data_root,
        session=session,
        chunk_text=cleaned_text,
        commands=commands,
        segments=segments,
    )
    public_text = str(session_payload.get("text") if session_payload else cleaned_text)
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
            "transcript_chars": len(public_text),
            "chunk_transcript_chars": len(cleaned_text),
            "profile": str(result.get("profile") or ""),
            "beam_size": int(result.get("beam_size") or 0),
            "worker": result.get("worker") if isinstance(result.get("worker"), dict) else {},
            "metrics": metrics,
            "session": public_session_metadata(session_payload),
            "source": source,
            "retention": "metadata_only",
        },
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


def transcription_metrics(*, result: dict, transcription_seconds: float, duration_seconds: float) -> dict:
    worker = result.get("worker") if isinstance(result.get("worker"), dict) else {}
    model_load_seconds = float(worker.get("model_load_seconds") or worker.get("startup_model_load_seconds") or 0.0)
    realtime_factor = transcription_seconds / duration_seconds if duration_seconds > 0 else 0.0
    return {
        "transcription_seconds": round(max(0.0, transcription_seconds), 6),
        "audio_duration_seconds": round(max(0.0, duration_seconds), 6),
        "realtime_factor": round(max(0.0, realtime_factor), 6),
        "cold_start": bool(worker.get("cold_start")),
        "model_load_seconds": round(max(0.0, model_load_seconds), 6),
    }


def public_session_metadata(session_payload: dict) -> dict:
    return {
        key: session_payload[key]
        for key in ("session_id", "chunk_index", "partial", "final")
        if key in session_payload
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
) -> dict:
    if not session:
        return {}
    cleanup_transcription_sessions(data_root)
    session_id = str(session["session_id"])
    chunk_index = int(session["chunk_index"])
    final = bool(session["final"])
    state = read_transcription_session(data_root, session_id)
    text = str(state.get("text") or "")
    if any(command.get("type") == "delete_last_sentence" for command in commands):
        text = delete_last_sentence(text)
    elif chunk_text:
        text = append_dictation_text(text, chunk_text)
    chunks = state.get("chunks") if isinstance(state.get("chunks"), list) else []
    chunks.append({"chunk_index": chunk_index, "text_chars": len(chunk_text), "segments": len(segments)})
    state = {"schema_version": "1", "session_id": session_id, "text": text, "chunks": chunks[-200:]}
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
