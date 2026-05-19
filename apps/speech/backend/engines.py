"""Local speech engine discovery and execution."""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
from pathlib import Path
import queue
import shutil
import subprocess
from tempfile import TemporaryDirectory

from errors import SpeechProviderUnavailableError, SpeechTranscriptionError
from models import DEFAULT_FASTER_WHISPER_COMPUTE_TYPE, DEFAULT_FASTER_WHISPER_DEVICE, DEFAULT_FASTER_WHISPER_MODEL

LOCAL_TTS_ENGINE_CANDIDATES = ("espeak", "espeak-ng")
WHISPER_CPP_BINARY_CANDIDATES = ("whisper-cli", "main")
FASTER_WHISPER_TIMEOUT_SECONDS = 240
FASTER_WHISPER_MODEL_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}


class LocalEngine:
    def __init__(self, *, name: str, path: str) -> None:
        self.name = name
        self.path = path


def resolve_local_tts_engine() -> LocalEngine | None:
    for name in LOCAL_TTS_ENGINE_CANDIDATES:
        path = shutil.which(name)
        if path:
            return LocalEngine(name=name, path=path)
    return None


def run_local_tts_engine(engine: LocalEngine, *, text: str, voice: str, rate: int) -> bytes:
    with TemporaryDirectory(prefix="maverick-speech-") as temp_dir:
        output_path = Path(temp_dir) / "speech.wav"
        command = [engine.path, "-w", str(output_path), "-s", str(rate), "-v", voice, text]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Local TTS engine failed.").strip()
            raise SpeechProviderUnavailableError(detail)
        if not output_path.exists():
            raise SpeechProviderUnavailableError("Local TTS engine did not produce audio.")
        return output_path.read_bytes()


def faster_whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def faster_whisper_model_ref() -> str:
    return os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_MODEL", DEFAULT_FASTER_WHISPER_MODEL).strip() or DEFAULT_FASTER_WHISPER_MODEL


def faster_whisper_device() -> str:
    return os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_DEVICE", DEFAULT_FASTER_WHISPER_DEVICE).strip() or DEFAULT_FASTER_WHISPER_DEVICE


def faster_whisper_compute_type() -> str:
    return os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE", DEFAULT_FASTER_WHISPER_COMPUTE_TYPE).strip() or DEFAULT_FASTER_WHISPER_COMPUTE_TYPE


def faster_whisper_model_label() -> str:
    model_ref = faster_whisper_model_ref()
    if _looks_like_path(model_ref):
        return "local-path"
    return model_ref


def faster_whisper_model_configured() -> bool:
    return _faster_whisper_model_is_local(faster_whisper_model_ref())


def _looks_like_path(value: str) -> bool:
    return value.startswith(("/", "./", "../", "~")) or "\\" in value


def _faster_whisper_repo_id(model_ref: str) -> str:
    return FASTER_WHISPER_MODEL_REPOS.get(model_ref, model_ref)


def _faster_whisper_model_is_local(model_ref: str) -> bool:
    if not model_ref:
        return False
    expanded_path = Path(model_ref).expanduser()
    if expanded_path.exists():
        return True
    if _looks_like_path(model_ref):
        return False
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return False
    try:
        snapshot_download(_faster_whisper_repo_id(model_ref), local_files_only=True)
    except Exception:
        return False
    return True


def resolve_whisper_cpp_binary() -> str:
    configured = os.environ.get("MAVERICK_SPEECH_WHISPER_CPP_BINARY", "").strip()
    if configured:
        return configured if Path(configured).exists() else ""
    for name in WHISPER_CPP_BINARY_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return ""


def whisper_cpp_model_path(settings: dict) -> str:
    return os.environ.get("MAVERICK_SPEECH_WHISPER_CPP_MODEL", "").strip()


def whisper_cpp_model_configured() -> bool:
    model_path = whisper_cpp_model_path({})
    return bool(model_path and Path(model_path).exists())


def transcription_engine_statuses(settings: dict) -> list[dict]:
    whisper_cpp_model = whisper_cpp_model_path(settings)
    whisper_cpp_binary = resolve_whisper_cpp_binary()
    faster_whisper_ready = faster_whisper_available() and faster_whisper_model_configured()
    return [
        {
            "engine": "faster-whisper",
            "kind": "stt",
            "available": faster_whisper_ready,
            "configured": faster_whisper_model_configured(),
            "detail": "Local faster-whisper package and model are available."
            if faster_whisper_ready
            else "Install the optional speech dependency and preinstall the faster-whisper model locally.",
            "model": faster_whisper_model_label(),
            "local_files_only": True,
        },
        {
            "engine": "whisper.cpp",
            "kind": "stt",
            "available": bool(whisper_cpp_binary and whisper_cpp_model and Path(whisper_cpp_model).exists()),
            "configured": bool(whisper_cpp_model),
            "detail": "whisper.cpp binary and model are configured."
            if whisper_cpp_binary and whisper_cpp_model and Path(whisper_cpp_model).exists()
            else "Set MAVERICK_SPEECH_WHISPER_CPP_BINARY and MAVERICK_SPEECH_WHISPER_CPP_MODEL to local installation paths.",
            "binary_configured": bool(whisper_cpp_binary),
            "model_configured": bool(whisper_cpp_model and Path(whisper_cpp_model).exists()),
        },
    ]


def synthesis_engine_statuses() -> list[dict]:
    engine = resolve_local_tts_engine()
    return [
        {
            "engine": candidate,
            "kind": "tts",
            "available": bool(engine and engine.name == candidate),
            "configured": True,
            "detail": "Local engine found on PATH." if engine and engine.name == candidate else "Local engine not found on PATH.",
            "binary_configured": bool(engine and engine.name == candidate),
        }
        for candidate in LOCAL_TTS_ENGINE_CANDIDATES
    ]


def resolve_transcription_engine(settings: dict) -> str:
    requested = str(settings.get("transcription_engine") or "auto").strip()
    statuses = {item["engine"]: item for item in transcription_engine_statuses(settings)}
    if requested == "auto":
        for engine in ("faster-whisper", "whisper.cpp"):
            if statuses.get(engine, {}).get("available"):
                return engine
        return ""
    return requested if statuses.get(requested, {}).get("available") else ""


def transcribe_audio_file(audio_path: Path, *, settings: dict, language: str = "") -> dict:
    engine = resolve_transcription_engine(settings)
    if engine == "faster-whisper":
        return _transcribe_with_faster_whisper(audio_path, settings=settings, language=language)
    if engine == "whisper.cpp":
        return _transcribe_with_whisper_cpp(audio_path, settings=settings, language=language)
    raise SpeechProviderUnavailableError("No configured speech-to-text engine is available.")


def _transcribe_with_faster_whisper(audio_path: Path, *, settings: dict, language: str = "") -> dict:
    config = {
        "model": faster_whisper_model_ref(),
        "model_label": faster_whisper_model_label(),
        "device": faster_whisper_device(),
        "compute_type": faster_whisper_compute_type(),
    }
    start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    context = multiprocessing.get_context(start_method)
    result_queue = context.Queue()
    process = context.Process(
        target=_faster_whisper_worker,
        args=(str(audio_path), config, language, result_queue),
    )
    process.start()
    process.join(FASTER_WHISPER_TIMEOUT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        raise SpeechTranscriptionError("faster-whisper transcription timed out.")
    try:
        payload = result_queue.get_nowait()
    except queue.Empty as error:
        raise SpeechTranscriptionError("faster-whisper transcription failed without returning a result.") from error
    if not payload.get("ok"):
        detail = str(payload.get("detail") or "faster-whisper transcription failed.")
        if payload.get("error_type") == "ImportError":
            raise SpeechProviderUnavailableError("faster-whisper is not installed.")
        raise SpeechTranscriptionError(detail)
    return payload["result"]


def _faster_whisper_worker(audio_path: str, config: dict, language: str, result_queue: multiprocessing.Queue) -> None:
    try:
        result_queue.put({"ok": True, "result": _run_faster_whisper_in_process(Path(audio_path), config=config, language=language)})
    except Exception as error:
        result_queue.put({"ok": False, "error_type": error.__class__.__name__, "detail": str(error)})


def _run_faster_whisper_in_process(audio_path: Path, *, config: dict, language: str = "") -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise SpeechProviderUnavailableError("faster-whisper is not installed.") from error

    model_name = str(config.get("model") or DEFAULT_FASTER_WHISPER_MODEL)
    device = str(config.get("device") or DEFAULT_FASTER_WHISPER_DEVICE)
    compute_type = str(config.get("compute_type") or DEFAULT_FASTER_WHISPER_COMPUTE_TYPE)
    kwargs = {"device": device, "local_files_only": True}
    if compute_type != "default":
        kwargs["compute_type"] = compute_type
    model = WhisperModel(model_name, **kwargs)
    try:
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language or None,
            vad_filter=True,
            word_timestamps=False,
        )
        segments = [
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
            }
            for segment in segments_iter
            if segment.text and segment.text.strip()
        ]
    except Exception as error:
        raise SpeechTranscriptionError(str(error)) from error
    return {
        "engine": "faster-whisper",
        "model": str(config.get("model_label") or "local-model"),
        "language": str(getattr(info, "language", "") or language or ""),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "duration_seconds": float(getattr(info, "duration", 0.0) or 0.0),
        "segments": segments,
        "text": " ".join(segment["text"] for segment in segments).strip(),
    }


def _transcribe_with_whisper_cpp(audio_path: Path, *, settings: dict, language: str = "") -> dict:
    binary = resolve_whisper_cpp_binary()
    model_path = whisper_cpp_model_path(settings)
    if not binary or not model_path or not Path(model_path).exists():
        raise SpeechProviderUnavailableError("whisper.cpp requires a binary and model path.")
    with TemporaryDirectory(prefix="maverick-speech-stt-") as temp_dir:
        output_prefix = Path(temp_dir) / "transcript"
        command = [binary, "-m", model_path, "-f", str(audio_path), "-otxt", "-of", str(output_prefix)]
        if language:
            command.extend(["-l", language])
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=240)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "whisper.cpp transcription failed.").strip()
            raise SpeechTranscriptionError(detail)
        output_path = output_prefix.with_suffix(".txt")
        text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else result.stdout.strip()
        return {
            "engine": "whisper.cpp",
            "model": "local-path",
            "language": language,
            "language_probability": 0.0,
            "duration_seconds": 0.0,
            "segments": [{"start": 0.0, "end": 0.0, "text": text}] if text else [],
            "text": text,
        }
