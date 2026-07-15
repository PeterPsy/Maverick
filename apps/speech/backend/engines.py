"""Local speech engine discovery and execution."""

from __future__ import annotations

import importlib.util
import base64
import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import uuid
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request

from errors import SpeechProviderUnavailableError, SpeechTranscriptionError
from kokoro_streaming import (
    KOKORO_DEEPINFRA_MODEL,
    KOKORO_OPENROUTER_DEFAULT_VOICE,
    KOKORO_OPENROUTER_MODEL,
    KOKORO_PCM_CONTENT_TYPE,
    collect_kokoro_deepinfra_audio,
    collect_kokoro_openrouter_audio,
)
from models import (
    DEFAULT_FASTER_WHISPER_COMPUTE_TYPE,
    DEFAULT_FASTER_WHISPER_DEVICE,
    DEFAULT_FASTER_WHISPER_MODEL,
    DEFAULT_INLINE_TRANSCRIPTION_PROFILE,
    DEFAULT_TRANSCRIPTION_PROFILE,
    TRANSCRIPTION_PROFILE_BEAM_SIZES,
    TRANSCRIPTION_PROFILE_COMPUTE_TYPE_DEFAULTS,
    TRANSCRIPTION_PROFILE_DEVICE_DEFAULTS,
    TRANSCRIPTION_PROFILE_MODELS,
    TTS_CACHE_HASH_MAX_BYTES,
)

DEEPGRAM_AUDIO_TRANSCRIPTION_MODEL = "nova-3"
DEEPGRAM_CONVERSATION_MODEL = "flux-general-multi"
KOKORO_OPENROUTER_RESPONSE_FORMAT = "mp3"
KOKORO_OPENROUTER_CONTENT_TYPE = "audio/mpeg"
KOKORO_OPENROUTER_LANGUAGE_DEFAULT_VOICES = {
    "en": KOKORO_OPENROUTER_DEFAULT_VOICE,
    "it": "if_sara",
}
KOKORO_OPENROUTER_VOICES = (
    {"voice_id": "af_heart", "name": "Heart", "language": "en", "gender": "female"},
    {"voice_id": "if_sara", "name": "Sara", "language": "it", "gender": "female"},
    {"voice_id": "im_nicola", "name": "Nicola", "language": "it", "gender": "male"},
)
REMOTE_PROVIDER_TIMEOUT_SECONDS = 45

LOCAL_TTS_ENGINE_CANDIDATES = ("piper", "espeak-ng", "espeak")
WHISPER_CPP_BINARY_CANDIDATES = ("whisper-cli", "main")
FASTER_WHISPER_TIMEOUT_SECONDS = 240
FASTER_WHISPER_QUEUE_TIMEOUT_SECONDS = 5
FASTER_WHISPER_WORKER_START_TIMEOUT_SECONDS = 20
FASTER_WHISPER_INITIAL_PROMPT_MAX_CHARS = 2000
PIPER_TTS_TIMEOUT_SECONDS = 60
PIPER_WORKER_START_TIMEOUT_SECONDS = 20
SYNTHESIS_DISCOVERY_CACHE_SECONDS = 10
MODEL_DIRECTORY_FINGERPRINT_FILES = (
    "config.json",
    "generation_config.json",
    "model_index.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "vocabulary.json",
    "vocabulary.txt",
    "merges.txt",
)
MODEL_DIRECTORY_WEIGHT_PATTERNS = (
    "model.bin",
    "*.bin",
    "*.safetensors",
)
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
_FASTER_WHISPER_LOCK = threading.Lock()
_FASTER_WHISPER_WORKER: dict | None = None
_EXTERNAL_WORKER_PROCESSES: dict[int, subprocess.Popen] = {}
_SYNTHESIS_STATUS_CACHE: dict[tuple[object, ...], tuple[float, list[dict]]] = {}
_LOCAL_SPEECH_ENV_LOADED = False


def _load_local_speech_env() -> None:
    """Load optional installation-local Speech engine settings."""

    global _LOCAL_SPEECH_ENV_LOADED
    if _LOCAL_SPEECH_ENV_LOADED:
        return
    _LOCAL_SPEECH_ENV_LOADED = True
    configured = os.environ.get("MAVERICK_SPEECH_ENV_FILE", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    if not configured and not _running_from_app_entrypoint():
        return
    candidates.append(Path(__file__).resolve().parents[3] / ".maverick" / "speech.env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        _apply_speech_env_file(env_path)
        return


def _running_from_app_entrypoint() -> bool:
    app_root = Path(__file__).resolve().parents[1]
    try:
        if Path.cwd().resolve() == app_root:
            return True
    except OSError:
        return False
    try:
        argv0 = Path(sys.argv[0]).resolve()
    except (OSError, RuntimeError):
        return False
    return argv0 == app_root or app_root in argv0.parents


def _apply_speech_env_file(env_path: Path) -> None:
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key != "PATH" and not key.startswith("MAVERICK_SPEECH_"):
            continue
        value = os.path.expandvars(raw_value.strip().strip("'\""))
        if key == "PATH":
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


_load_local_speech_env()


@dataclass(frozen=True)
class LocalEngine:
    name: str
    path: str
    quality_profile: str = "diagnostic"
    latency_profile: str = "low"
    content_type: str = "audio/wav"
    voice_id: str = ""
    voices: tuple[dict, ...] = ()


def resolve_local_tts_engine(settings: dict | None = None) -> LocalEngine | None:
    requested = str((settings or {}).get("synthesis_engine") or "auto").strip()
    statuses = {item["engine"]: item for item in synthesis_engine_statuses(include_paths=True)}
    candidates = LOCAL_TTS_ENGINE_CANDIDATES if requested == "auto" else (requested,)
    for name in candidates:
        status = statuses.get(name) or {}
        path = str(status.get("path") or "")
        if status.get("available") and path:
            voices = tuple(item for item in (status.get("voices") or []) if isinstance(item, dict))
            return LocalEngine(
                name=name,
                path=path,
                quality_profile=str(status.get("quality_profile") or "diagnostic"),
                latency_profile=str(status.get("latency_profile") or "low"),
                content_type="audio/wav",
                voice_id=default_tts_voice_id(name, voices),
                voices=voices,
            )
    return None


def run_local_tts_engine(engine: LocalEngine, *, text: str, voice: str, rate: int, data_root: Path | None = None) -> bytes:
    if engine.name == "piper":
        return _run_piper_tts_engine(engine, text=text, voice=voice, data_root=data_root)
    return _run_espeak_tts_engine(engine, text=text, voice=voice, rate=rate)


def run_kokoro_openrouter(*, text: str, voice: str, settings: dict) -> bytes:
    return collect_kokoro_openrouter_audio(
        text=text,
        voice=voice,
        settings=settings,
        response_format=KOKORO_OPENROUTER_RESPONSE_FORMAT,
    )


def run_kokoro_deepinfra(*, text: str, voice: str, language: str, settings: dict) -> bytes:
    return collect_kokoro_deepinfra_audio(
        text=text,
        voice=voice,
        language=language,
        settings=settings,
        response_format=KOKORO_OPENROUTER_RESPONSE_FORMAT,
    )


def _run_espeak_tts_engine(engine: LocalEngine, *, text: str, voice: str, rate: int) -> bytes:
    with TemporaryDirectory(prefix="maverick-speech-") as temp_dir:
        output_path = Path(temp_dir) / "speech.wav"
        command = [engine.path, "-w", str(output_path), "-s", str(rate), "-v", voice, "--stdin"]
        result = subprocess.run(command, input=text, check=False, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Local TTS engine failed.").strip()
            raise SpeechProviderUnavailableError(detail)
        if not output_path.exists():
            raise SpeechProviderUnavailableError("Local TTS engine did not produce audio.")
        return output_path.read_bytes()


def _run_piper_tts_engine(engine: LocalEngine, *, text: str, voice: str, data_root: Path | None = None) -> bytes:
    voice_profile = piper_voice_profile(engine, voice)
    if voice_profile.get("_from_registry") and not voice_profile.get("_model_path"):
        raise SpeechProviderUnavailableError(f"Piper voice `{voice}` does not have a configured local model.")
    model_path = str(voice_profile.get("_model_path") or piper_model_path())
    if not model_path:
        raise SpeechProviderUnavailableError("Piper requires MAVERICK_SPEECH_PIPER_MODEL to point at a local voice model.")
    if data_root is not None and persistent_piper_worker_enabled():
        if piper_python_available():
            try:
                return _run_external_piper_worker_job(data_root, engine, voice_profile, text=text)
            except (OSError, TimeoutError, SpeechProviderUnavailableError) as error:
                if strict_piper_worker_enabled():
                    raise SpeechProviderUnavailableError(
                        f"Piper persistent worker failed: {error.__class__.__name__}: {error}. "
                        "Set MAVERICK_SPEECH_PIPER_WORKER=auto or entrypoint to allow fallback."
                    ) from error
        elif strict_piper_worker_enabled():
            raise SpeechProviderUnavailableError("Piper persistent worker requires the piper-tts Python package.")
    with TemporaryDirectory(prefix="maverick-speech-") as temp_dir:
        output_path = Path(temp_dir) / "speech.wav"
        command = [engine.path, "--model", model_path, "--output_file", str(output_path)]
        config_path = str(voice_profile.get("_config_path") or piper_config_path())
        if config_path:
            command.extend(["--config", config_path])
        result = subprocess.run(command, input=text, check=False, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Piper TTS engine failed.").strip()
            raise SpeechProviderUnavailableError(detail)
        if not output_path.exists():
            raise SpeechProviderUnavailableError("Piper TTS engine did not produce audio.")
        return output_path.read_bytes()


def prewarm_local_tts_worker(data_root: Path, engine: LocalEngine, *, voice: str) -> dict:
    if engine.name != "piper":
        return {
            "supported": False,
            "warmed": False,
            "engine": engine.name,
            "voice": voice,
            "reason": "selected_engine_does_not_use_a_persistent_tts_worker",
        }
    if not persistent_piper_worker_enabled() or not piper_python_available():
        return {
            "supported": False,
            "warmed": False,
            "engine": engine.name,
            "voice": voice,
            "reason": "persistent_piper_worker_unavailable",
        }
    voice_profile = piper_voice_profile(engine, voice)
    if voice_profile.get("_from_registry") and not voice_profile.get("_model_path"):
        raise SpeechProviderUnavailableError(f"Piper voice `{voice}` does not have a configured local model.")
    config = _piper_worker_config(engine, voice_profile)
    paths = _piper_worker_paths(data_root, config)
    ready_before_request = _external_worker_accepts_connection(paths["socket"])
    started = time.monotonic()
    _ensure_external_piper_worker(
        config,
        socket_path=paths["socket"],
        pid_path=paths["pid"],
        lock_path=paths["lock"],
    )
    return {
        "supported": True,
        "warmed": True,
        "engine": engine.name,
        "voice": str(voice_profile.get("voice_id") or voice),
        "scope": "workspace_daemon",
        "worker_id": paths["socket"].stem,
        "ready_before_request": ready_before_request,
        "prewarm_seconds": round(time.monotonic() - started, 6),
    }


def piper_worker_mode() -> str:
    return os.environ.get("MAVERICK_SPEECH_PIPER_WORKER", "auto").strip().lower() or "auto"


def piper_python_available() -> bool:
    try:
        return importlib.util.find_spec("piper.voice") is not None
    except ModuleNotFoundError:
        return False


def persistent_piper_worker_enabled() -> bool:
    return piper_worker_mode() not in {"0", "false", "no", "off", "entrypoint", "process", "disabled"}


def strict_piper_worker_enabled() -> bool:
    return piper_worker_mode() == "persistent"


def _run_external_piper_worker_job(data_root: Path, engine: LocalEngine, voice_profile: dict, *, text: str) -> bytes:
    config = _piper_worker_config(engine, voice_profile)
    paths = _piper_worker_paths(data_root, config)
    _ensure_external_piper_worker(config, socket_path=paths["socket"], pid_path=paths["pid"], lock_path=paths["lock"])
    output_dir = data_root / "run" / "piper-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"tts-{uuid.uuid4().hex}.wav"
    try:
        payload = _send_external_piper_job(paths["socket"], {"text": text, "output_path": str(output_path)})
        if not payload.get("ok"):
            raise SpeechProviderUnavailableError(str(payload.get("detail") or "Piper persistent worker failed."))
        if payload.get("audio_base64"):
            try:
                return base64.b64decode(str(payload.get("audio_base64") or ""), validate=True)
            except ValueError as error:
                raise SpeechProviderUnavailableError("Piper persistent worker returned invalid audio.") from error
        if not output_path.exists() or not output_path.is_file():
            raise SpeechProviderUnavailableError("Piper persistent worker did not produce audio.")
        return output_path.read_bytes()
    finally:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass


def _piper_worker_config(engine: LocalEngine, voice_profile: dict) -> dict:
    model_path = str(voice_profile.get("_model_path") or piper_model_path())
    config_path = str(voice_profile.get("_config_path") or piper_config_path())
    return {
        "engine_path": engine.path,
        "voice_id": str(voice_profile.get("voice_id") or engine.voice_id or "piper-local"),
        "model_path": model_path,
        "config_path": config_path,
        "model": _file_fingerprint(model_path),
        "config": _file_fingerprint(config_path),
    }


def _piper_worker_paths(data_root: Path, config: dict) -> dict[str, Path]:
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    run_dir = data_root / "run"
    return {
        "socket": run_dir / f"piper-{digest}.sock",
        "pid": run_dir / f"piper-{digest}.pid",
        "lock": run_dir / f"piper-{digest}.lock",
        "log": run_dir / f"piper-{digest}.log",
    }


def _ensure_external_piper_worker(config: dict, *, socket_path: Path, pid_path: Path, lock_path: Path) -> None:
    if _external_worker_accepts_connection(socket_path):
        return
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    with _locked_worker_start(lock_path):
        if _external_worker_accepts_connection(socket_path):
            return
        paths = {"socket": socket_path, "pid": pid_path, "lock": lock_path, "log": lock_path.with_suffix(".log")}
        _remove_stale_external_worker_files(socket_path, pid_path, script_name="tts_worker.py")
        with paths["log"].open("ab") as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("tts_worker.py")),
                    "--socket",
                    str(socket_path),
                    "--pid-file",
                    str(pid_path),
                    "--config-json",
                    json.dumps(config, sort_keys=True),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                close_fds=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + PIPER_WORKER_START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if _external_worker_accepts_connection(socket_path):
                    _EXTERNAL_WORKER_PROCESSES[process.pid] = process
                    return
                if process.poll() is not None:
                    break
                time.sleep(0.1)
    raise SpeechProviderUnavailableError("Piper persistent worker did not become ready.")


def _send_external_piper_job(socket_path: Path, request: dict) -> dict:
    deadline = time.monotonic() + PIPER_TTS_TIMEOUT_SECONDS
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(socket_path))
        client.sendall((json.dumps(request, sort_keys=True) + "\n").encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            client.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
            try:
                chunk = client.recv(1024 * 1024)
            except socket.timeout:
                continue
            if not chunk:
                break
            chunks.append(chunk)
    if not chunks:
        raise SpeechProviderUnavailableError("Piper persistent worker returned an empty response.")
    return json.loads(b"".join(chunks).decode("utf-8"))


def stop_piper_workers(data_root: Path) -> dict:
    stopped: list[dict] = []
    run_dir = data_root / "run"
    for pid_path in sorted(run_dir.glob("piper-*.pid")) if run_dir.exists() else []:
        stem = pid_path.stem
        socket_path = run_dir / f"{stem}.sock"
        pid = _read_worker_pid(pid_path)
        stopped.append(
            {
                "worker_id": stem,
                "pid": pid,
                "terminated": bool(pid and _pid_matches_worker(pid, socket_path, script_name="tts_worker.py") and _terminate_worker_pid(pid)),
            }
        )
        _remove_stale_external_worker_files(socket_path, pid_path, script_name="tts_worker.py")
    return {"stopped": stopped, "count": len(stopped)}


def piper_model_path() -> str:
    model_path = os.environ.get("MAVERICK_SPEECH_PIPER_MODEL", "").strip()
    expanded = Path(model_path).expanduser() if model_path else Path()
    return str(expanded) if model_path and expanded.exists() else ""


def piper_config_path() -> str:
    config_path = os.environ.get("MAVERICK_SPEECH_PIPER_CONFIG", "").strip()
    expanded = Path(config_path).expanduser() if config_path else Path()
    return str(expanded) if config_path and expanded.exists() else ""


def piper_voice_profile(engine: LocalEngine, voice: str) -> dict:
    requested = voice or engine.voice_id
    for profile in engine.voices:
        if str(profile.get("voice_id") or "") == requested:
            return profile
    if engine.voices:
        return engine.voices[0]
    return {"voice_id": requested, "_model_path": piper_model_path(), "_config_path": piper_config_path()}


def faster_whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def faster_whisper_model_ref(settings: dict | None = None) -> str:
    profile = transcription_profile(settings)
    configured = os.environ.get(f"MAVERICK_SPEECH_FASTER_WHISPER_{profile.upper()}_MODEL", "").strip()
    if configured:
        return configured
    global_configured = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_MODEL", "").strip()
    if global_configured and (profile == DEFAULT_TRANSCRIPTION_PROFILE or faster_whisper_global_model_applies_to_all_profiles()):
        return global_configured
    return transcription_profile_model(settings)


def faster_whisper_global_model_applies_to_all_profiles() -> bool:
    value = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def transcription_profile(settings: dict | None = None) -> str:
    profile = str((settings or {}).get("transcription_profile") or DEFAULT_TRANSCRIPTION_PROFILE).strip()
    return profile if profile in TRANSCRIPTION_PROFILE_MODELS else DEFAULT_TRANSCRIPTION_PROFILE


def transcription_profile_model(settings: dict | None = None) -> str:
    return TRANSCRIPTION_PROFILE_MODELS[transcription_profile(settings)]


def faster_whisper_beam_size(settings: dict | None = None) -> int:
    configured = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_BEAM_SIZE", "").strip()
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            return TRANSCRIPTION_PROFILE_BEAM_SIZES[transcription_profile(settings)]
    return TRANSCRIPTION_PROFILE_BEAM_SIZES[transcription_profile(settings)]


def faster_whisper_device(settings: dict | None = None) -> str:
    configured = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_DEVICE", "").strip()
    if configured:
        return configured
    return TRANSCRIPTION_PROFILE_DEVICE_DEFAULTS.get(transcription_profile(settings), DEFAULT_FASTER_WHISPER_DEVICE)


def faster_whisper_compute_type(settings: dict | None = None) -> str:
    configured = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE", "").strip()
    if configured:
        return configured
    return TRANSCRIPTION_PROFILE_COMPUTE_TYPE_DEFAULTS.get(transcription_profile(settings), DEFAULT_FASTER_WHISPER_COMPUTE_TYPE)


def faster_whisper_initial_prompt() -> str:
    prompt = os.environ.get("MAVERICK_SPEECH_TRANSCRIPTION_PROMPT", "").strip()
    glossary = os.environ.get("MAVERICK_SPEECH_TRANSCRIPTION_GLOSSARY", "").strip()
    glossary_file = os.environ.get("MAVERICK_SPEECH_TRANSCRIPTION_GLOSSARY_FILE", "").strip()
    if glossary_file:
        try:
            glossary_from_file = Path(glossary_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            glossary_from_file = ""
        glossary = "\n".join(item for item in (glossary, glossary_from_file) if item)
    parts = []
    if prompt:
        parts.append(prompt)
    if glossary:
        parts.append(f"Prefer these workspace terms, names, apps, and commands: {glossary}")
    return "\n".join(parts).strip()[:FASTER_WHISPER_INITIAL_PROMPT_MAX_CHARS]


def faster_whisper_model_label(settings: dict | None = None) -> str:
    model_ref = faster_whisper_model_ref(settings)
    if _looks_like_path(model_ref):
        return "local-path"
    return model_ref


def faster_whisper_model_source(settings: dict | None = None) -> str:
    profile = transcription_profile(settings)
    if os.environ.get(f"MAVERICK_SPEECH_FASTER_WHISPER_{profile.upper()}_MODEL", "").strip():
        return "profile_env"
    if os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_MODEL", "").strip() and (
        profile == DEFAULT_TRANSCRIPTION_PROFILE or faster_whisper_global_model_applies_to_all_profiles()
    ):
        return "global_env"
    return "profile_default"


def faster_whisper_model_configured(settings: dict | None = None) -> bool:
    return _faster_whisper_model_is_local(faster_whisper_model_ref(settings))


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
    faster_whisper_ready = faster_whisper_available() and faster_whisper_model_configured(settings)
    return [
        {
            "engine": "faster-whisper",
            "kind": "stt",
            "available": faster_whisper_ready,
            "configured": faster_whisper_model_configured(settings),
            "detail": "Local faster-whisper package and model are available."
            if faster_whisper_ready
            else "Install the optional speech dependency and preinstall the faster-whisper model locally.",
            "model": faster_whisper_model_label(settings),
            "model_source": faster_whisper_model_source(settings),
            "profile": transcription_profile(settings),
            "beam_size": faster_whisper_beam_size(settings),
            "device": faster_whisper_device(settings),
            "compute_type": faster_whisper_compute_type(settings),
            "initial_prompt_configured": bool(faster_whisper_initial_prompt()),
            "local_files_only": True,
            "persistent_worker": persistent_faster_whisper_worker_enabled(),
            "worker_mode": faster_whisper_worker_mode(),
            "worker_scope": "workspace_daemon" if persistent_faster_whisper_worker_enabled() else "entrypoint_process",
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
        {
            "engine": "deepgram",
            "kind": "stt",
            "available": bool(_runtime_secret(settings, "deepgram_api_key")),
            "configured": bool(_runtime_secret(settings, "deepgram_api_key")),
            "detail": "Deepgram Nova-3 API key was delivered by Core Secrets."
            if _runtime_secret(settings, "deepgram_api_key")
            else "Grant logical secret deepgram-api-key to the Speech backend.",
            "model": deepgram_model_for("transcribe_audio", "one_shot", settings=settings),
            "conversation_model": deepgram_model_for("conversation_stream", "conversation", settings=settings),
            "model_source": "deepgram",
            "profile": "remote",
            "streaming_supported": True,
        },
    ]


def synthesis_engine_statuses(settings: dict | None = None, *, include_paths: bool = False) -> list[dict]:
    key = _synthesis_status_cache_key(include_paths=include_paths, settings=settings)
    now = time.monotonic()
    cached = _SYNTHESIS_STATUS_CACHE.get(key)
    if cached and now - cached[0] <= SYNTHESIS_DISCOVERY_CACHE_SECONDS:
        return copy.deepcopy(cached[1])
    statuses = [
        *[_synthesis_engine_status(candidate, include_path=include_paths) for candidate in LOCAL_TTS_ENGINE_CANDIDATES],
        _remote_kokoro_openrouter_status(settings or {}),
        _remote_kokoro_deepinfra_status(settings or {}),
    ]
    _SYNTHESIS_STATUS_CACHE[key] = (now, copy.deepcopy(statuses))
    return statuses


def _synthesis_status_cache_key(*, include_paths: bool, settings: dict | None = None) -> tuple[object, ...]:
    return (
        include_paths,
        os.environ.get("PATH", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_MODEL", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_CONFIG", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_MODEL_SHA256", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_CONFIG_SHA256", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_VOICE_ID", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_LANGUAGE", ""),
        os.environ.get("MAVERICK_SPEECH_PIPER_VOICES_JSON", ""),
        bool(_runtime_secret(settings or {}, "openrouter_api_key")),
        bool(_runtime_secret(settings or {}, "deepinfra_api_key")),
    )


def _remote_kokoro_openrouter_status(settings: dict) -> dict:
    configured = bool(_runtime_secret(settings, "openrouter_api_key"))
    return {
        "engine": "kokoro-openrouter",
        "kind": "tts",
        "available": configured,
        "configured": configured,
        "detail": "OpenRouter API key was delivered by Core Secrets."
        if configured
        else "Grant logical secret openrouter-api-key to the Speech backend.",
        "model": KOKORO_OPENROUTER_MODEL,
        "quality_profile": "natural",
        "latency_profile": "remote",
        "supported_formats": [KOKORO_OPENROUTER_CONTENT_TYPE, KOKORO_PCM_CONTENT_TYPE],
        "voices": [dict(voice) for voice in KOKORO_OPENROUTER_VOICES],
    }


def _remote_kokoro_deepinfra_status(settings: dict) -> dict:
    configured = bool(_runtime_secret(settings, "deepinfra_api_key"))
    return {
        "engine": "kokoro-deepinfra",
        "kind": "tts",
        "available": configured,
        "configured": configured,
        "detail": "DeepInfra API key was delivered by Core Secrets."
        if configured
        else "Grant logical secret deepinfra-api-key to the Speech backend.",
        "model": KOKORO_DEEPINFRA_MODEL,
        "quality_profile": "natural",
        "latency_profile": "remote_streaming",
        "supported_formats": [KOKORO_OPENROUTER_CONTENT_TYPE, KOKORO_PCM_CONTENT_TYPE],
        "voices": [dict(voice) for voice in KOKORO_OPENROUTER_VOICES],
    }


def _synthesis_engine_status(candidate: str, *, include_path: bool) -> dict:
    path = shutil.which(candidate) or ""
    if candidate == "piper":
        voices = piper_voice_profiles(include_paths=include_path)
        configured = bool(path and voices and any(item.get("model_configured") for item in voices))
        payload = {
            "engine": candidate,
            "kind": "tts",
            "available": configured,
            "configured": bool(voices and any(item.get("model_configured") for item in voices)),
            "detail": "Piper binary and local voice model are configured."
            if configured
            else "Install piper and set MAVERICK_SPEECH_PIPER_MODEL to a local voice model.",
            "binary_configured": bool(path),
            "model_configured": bool(voices and any(item.get("model_configured") for item in voices)),
            "quality_profile": "natural",
            "latency_profile": "medium",
            "persistent_worker": persistent_piper_worker_enabled() and piper_python_available(),
            "worker_mode": piper_worker_mode(),
            "worker_python_available": piper_python_available(),
            "worker_scope": "workspace_daemon" if persistent_piper_worker_enabled() and piper_python_available() else "entrypoint_process",
            "supported_formats": ["audio/wav"],
            "voices": voices,
            "fallback": "espeak-ng",
        }
        if include_path:
            payload["path"] = path
        return payload
    payload = {
        "engine": candidate,
        "kind": "tts",
        "available": bool(path),
        "configured": True,
        "detail": "Local engine found on PATH." if path else "Local engine not found on PATH.",
        "binary_configured": bool(path),
        "quality_profile": "diagnostic",
        "latency_profile": "low",
        "supported_formats": ["audio/wav"],
        "voices": espeak_voice_profiles(path) if path else [],
        "fallback": "",
    }
    if include_path:
        payload["path"] = path
    return payload


def default_tts_voice_id(engine_name: str, voices: tuple[dict, ...] | list[dict], *, language: str = "") -> str:
    if not voices:
        return "piper-local" if engine_name == "piper" else "en"
    language_voice = tts_voice_id_for_language(voices, language)
    if language_voice:
        return language_voice
    if engine_name == "piper":
        for profile in voices:
            if profile.get("model_configured"):
                return str(profile.get("voice_id") or "piper-local")
        return str(voices[0].get("voice_id") or "piper-local")
    ranked = sorted(((_english_voice_rank(profile), index, profile) for index, profile in enumerate(voices)), key=lambda item: (item[0], item[1]))
    best = ranked[0][2]
    return str(best.get("voice_id") or "en") if ranked[0][0] < 100 else str(voices[0].get("voice_id") or "en")


def tts_voice_id_for_language(voices: tuple[dict, ...] | list[dict], language: str) -> str:
    requested = language.strip().lower().replace("_", "-")
    if not requested or requested == "auto":
        return ""
    primary = requested.split("-", 1)[0]
    ranked: list[tuple[int, int, str]] = []
    for index, profile in enumerate(voices):
        profile_language = str(profile.get("language") or "").strip().lower().replace("_", "-")
        voice_id = str(profile.get("voice_id") or "")
        if not profile_language or not voice_id:
            continue
        profile_primary = profile_language.split("-", 1)[0]
        if profile_language == requested:
            ranked.append((0, index, voice_id))
        elif profile_primary == primary:
            ranked.append((1, index, voice_id))
    if not ranked:
        return ""
    return min(ranked, key=lambda item: (item[0], item[1]))[2]


def _english_voice_rank(profile: dict) -> int:
    voice_id = str(profile.get("voice_id") or "").strip().lower()
    language = str(profile.get("language") or "").strip().lower().replace("_", "-")
    name = str(profile.get("name") or "").strip().lower()
    if voice_id == "en":
        return 0
    if language == "en":
        return 1
    if language in {"en-us", "en-us+m1", "en-us+m2"} or "america" in voice_id or "america" in name or voice_id in {"english-us", "us"}:
        return 2
    if language in {"en-gb", "en-uk"} or "british" in voice_id or "british" in name or voice_id in {"english", "english_rp"}:
        return 3
    if language.startswith("en-"):
        return 10
    if language.startswith("en"):
        return 20
    return 100


def piper_voice_profiles(*, include_paths: bool = False) -> list[dict]:
    voice_id = os.environ.get("MAVERICK_SPEECH_PIPER_VOICE_ID", "").strip() or "piper-local"
    language = os.environ.get("MAVERICK_SPEECH_PIPER_LANGUAGE", "").strip() or ""
    configured = os.environ.get("MAVERICK_SPEECH_PIPER_VOICES_JSON", "").strip()
    if configured:
        try:
            payload = json.loads(configured)
        except json.JSONDecodeError:
            payload = []
        if isinstance(payload, list):
            voices = [_normalized_piper_voice_profile(item, include_paths=include_paths) for item in payload if isinstance(item, dict)]
            voices = [item for item in voices if item.get("voice_id")]
            if voices:
                return voices
    if not piper_model_path():
        return []
    profile = {
        "voice_id": voice_id,
        "language": language,
        "name": voice_id,
        "gender": "",
        "quality_profile": "natural",
        "model_configured": bool(piper_model_path()),
    }
    if include_paths:
        profile["_model_path"] = piper_model_path()
        profile["_config_path"] = piper_config_path()
        profile["_model_sha256"] = os.environ.get("MAVERICK_SPEECH_PIPER_MODEL_SHA256", "").strip().lower()
        profile["_config_sha256"] = os.environ.get("MAVERICK_SPEECH_PIPER_CONFIG_SHA256", "").strip().lower()
    return [profile]


def _normalized_piper_voice_profile(item: dict, *, include_paths: bool) -> dict:
    voice_id = str(item.get("voice_id") or item.get("id") or "").strip()
    if not voice_id:
        return {}
    model_path = _existing_path(str(item.get("model") or item.get("model_path") or ""))
    config_path = _existing_path(str(item.get("config") or item.get("config_path") or ""))
    profile = {
        "voice_id": voice_id,
        "language": str(item.get("language") or "").strip(),
        "name": str(item.get("name") or voice_id).strip(),
        "gender": str(item.get("gender") or "").strip(),
        "quality_profile": "natural",
        "model_configured": bool(model_path),
    }
    if include_paths:
        profile["_model_path"] = model_path
        profile["_config_path"] = config_path
        profile["_model_sha256"] = str(item.get("model_sha256") or item.get("sha256") or "").strip().lower()
        profile["_config_sha256"] = str(item.get("config_sha256") or "").strip().lower()
        profile["_from_registry"] = True
    return profile


def _existing_path(value: str) -> str:
    expanded = Path(value).expanduser() if value else Path()
    return str(expanded) if value and expanded.exists() else ""


def espeak_voice_profiles(path: str, *, limit: int = 80) -> list[dict]:
    if not path:
        return []
    try:
        result = subprocess.run([path, "--voices"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    voices: list[dict] = []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].lower().startswith("pty"):
            continue
        language = parts[1]
        voice_name = parts[3]
        voices.append(
            {
                "voice_id": language,
                "language": language,
                "name": voice_name,
                "gender": "",
                "quality_profile": "diagnostic",
            }
        )
        if len(voices) >= limit:
            break
    if not voices:
        voices.append({"voice_id": "en", "language": "en", "name": "en", "gender": "", "quality_profile": "diagnostic"})
    return voices


def tts_engine_cache_fingerprint(engine: LocalEngine, *, voice: str) -> dict:
    fingerprint = {
        "engine": engine.name,
        "binary": _file_fingerprint(engine.path),
        "quality_profile": engine.quality_profile,
    }
    if engine.name == "piper":
        profile = piper_voice_profile(engine, voice)
        fingerprint["voice_id"] = str(profile.get("voice_id") or voice)
        fingerprint["model"] = _file_fingerprint(
            str(profile.get("_model_path") or piper_model_path()),
            configured_sha256=str(profile.get("_model_sha256") or os.environ.get("MAVERICK_SPEECH_PIPER_MODEL_SHA256", "")),
        )
        fingerprint["config"] = _file_fingerprint(
            str(profile.get("_config_path") or piper_config_path()),
            configured_sha256=str(profile.get("_config_sha256") or os.environ.get("MAVERICK_SPEECH_PIPER_CONFIG_SHA256", "")),
        )
    return fingerprint


def _file_fingerprint(path_value: str, *, configured_sha256: str = "") -> dict:
    path = Path(path_value).expanduser() if path_value else Path()
    if not path_value or not path.exists():
        return {"configured": False}
    stat = path.stat()
    payload = {
        "configured": True,
        "kind": "directory" if path.is_dir() else "file",
        "name": path.name,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    digest = configured_sha256.strip().lower()
    if path.is_dir():
        payload["files"] = _directory_fingerprint_files(path)
    elif not digest and stat.st_size <= TTS_CACHE_HASH_MAX_BYTES:
        digest = _sha256_file(path)
    if digest:
        payload["sha256"] = digest
    return payload


def _directory_fingerprint_files(path: Path) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for relative_name in MODEL_DIRECTORY_FINGERPRINT_FILES:
        child = path / relative_name
        if not child.is_file():
            continue
        seen.add(relative_name)
        stat = child.stat()
        entry = {
            "name": relative_name,
            "kind": "metadata",
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if stat.st_size <= TTS_CACHE_HASH_MAX_BYTES:
            entry["sha256"] = _sha256_file(child)
        entries.append(entry)
    for pattern in MODEL_DIRECTORY_WEIGHT_PATTERNS:
        for child in sorted(path.glob(pattern)):
            if not child.is_file():
                continue
            relative_name = child.name
            if relative_name in seen:
                continue
            seen.add(relative_name)
            stat = child.stat()
            entries.append(
                {
                    "name": relative_name,
                    "kind": "weight_metadata",
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return entries


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_secret(settings: dict, logical_name: str) -> str:
    secrets = settings.get("_app_secrets") if isinstance(settings.get("_app_secrets"), dict) else {}
    value = None
    if isinstance(secrets, dict):
        value = secrets.get(logical_name)
        if value is None:
            value = secrets.get(logical_name.replace("_", "-"))
        if value is None:
            value = secrets.get(logical_name.replace("-", "_"))
    return str(value or "").strip()


def resolve_transcription_engine(settings: dict) -> str:
    requested = str(settings.get("transcription_engine") or "auto").strip()
    statuses = {item["engine"]: item for item in transcription_engine_statuses(settings)}
    if requested == "auto":
        for engine in ("faster-whisper", "whisper.cpp"):
            if statuses.get(engine, {}).get("available"):
                return engine
        return ""
    return requested if statuses.get(requested, {}).get("available") else ""


def transcribe_audio_file(
    audio_path: Path,
    *,
    settings: dict,
    language: str = "",
    operation: str = "transcribe_file",
    mode: str = "one_shot",
) -> dict:
    engine = resolve_transcription_engine(settings)
    if engine == "faster-whisper":
        return _transcribe_with_faster_whisper(audio_path, settings=settings, language=language)
    if engine == "whisper.cpp":
        return _transcribe_with_whisper_cpp(audio_path, settings=settings, language=language)
    if engine == "deepgram":
        return _transcribe_with_deepgram(audio_path, settings=settings, language=language, operation=operation, mode=mode)
    raise SpeechProviderUnavailableError("No configured speech-to-text engine is available.")


def deepgram_model_for(operation: str, mode: str = "one_shot", *, settings: dict | None = None) -> str:
    """Return the Deepgram model for one Speech operation."""
    normalized_operation = str(operation or "").strip()
    normalized_mode = str(mode or "").strip()
    if normalized_operation == "conversation_stream" or normalized_mode in {"conversation", "realtime_conversation"}:
        return _configured_deepgram_model(
            settings,
            "conversation_model_id",
            "deepgram_conversation_model_id",
            DEEPGRAM_CONVERSATION_MODEL,
        )
    return _configured_deepgram_model(
        settings,
        "audio_transcription_model_id",
        "deepgram_audio_transcription_model_id",
        DEEPGRAM_AUDIO_TRANSCRIPTION_MODEL,
    )


def _configured_deepgram_model(
    settings: dict | None,
    selection_key: str,
    settings_key: str,
    default_model_id: str,
) -> str:
    if isinstance(settings, dict):
        direct = str(settings.get(settings_key) or "").strip()
        if direct:
            return direct
        provider_config = settings.get("_provider_config") if isinstance(settings.get("_provider_config"), dict) else {}
        speech_config = provider_config.get("speech_stt") if isinstance(provider_config.get("speech_stt"), dict) else {}
        selected = str(speech_config.get(selection_key) or "").strip()
        if selected:
            return selected
        selection = speech_config.get("selection") if isinstance(speech_config.get("selection"), dict) else {}
        selected = str(selection.get(selection_key) or "").strip()
        if selected:
            return selected
        model_settings = speech_config.get("model_settings") if isinstance(speech_config.get("model_settings"), dict) else {}
        selected = str(model_settings.get(selection_key) or "").strip()
        if selected:
            return selected
    return default_model_id


def _transcribe_with_deepgram(
    audio_path: Path,
    *,
    settings: dict,
    language: str = "",
    operation: str = "transcribe_file",
    mode: str = "one_shot",
) -> dict:
    api_key = _runtime_secret(settings, "deepgram_api_key")
    if not api_key:
        raise SpeechProviderUnavailableError("Deepgram API key was not delivered to Speech.")
    model = deepgram_model_for(operation, mode, settings=settings)
    query = f"model={model}&smart_format=true&punctuate=true"
    if language:
        query += f"&language={language}"
    else:
        query += "&detect_language=true"
    request = urllib_request.Request(
        f"https://api.deepgram.com/v1/listen?{query}",
        data=audio_path.read_bytes(),
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": _audio_content_type_for_path(audio_path),
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=REMOTE_PROVIDER_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        raise SpeechTranscriptionError(f"Deepgram transcription failed with HTTP {error.code}.") from error
    except (urllib_error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SpeechTranscriptionError("Deepgram transcription failed.") from error
    alternative = _deepgram_best_alternative(payload)
    channel = _deepgram_first_channel(payload)
    text = str(alternative.get("transcript") or "")
    words = alternative.get("words") if isinstance(alternative.get("words"), list) else []
    return {
        "text": text,
        "segments": _deepgram_segments(words, fallback_text=text),
        "duration_seconds": float(payload.get("metadata", {}).get("duration") or 0.0)
        if isinstance(payload.get("metadata"), dict)
        else 0.0,
        "engine": "deepgram",
        "model": model,
        "language": _deepgram_detected_language(channel, fallback=language),
        "language_probability": _deepgram_language_confidence(channel),
    }


def _deepgram_first_channel(payload: dict) -> dict:
    channels = payload.get("results", {}).get("channels", []) if isinstance(payload.get("results"), dict) else []
    if not channels or not isinstance(channels[0], dict):
        return {}
    return channels[0]


def _deepgram_best_alternative(payload: dict) -> dict:
    channel = _deepgram_first_channel(payload)
    if not channel:
        return {}
    alternatives = channel.get("alternatives", [])
    if not alternatives or not isinstance(alternatives[0], dict):
        return {}
    return alternatives[0]


def _deepgram_detected_language(channel: dict, *, fallback: str = "") -> str:
    language = str(channel.get("detected_language") or fallback or "").strip().lower().replace("_", "-")
    if not language:
        return ""
    return language.split("-", 1)[0]


def _deepgram_language_confidence(channel: dict) -> float:
    try:
        return float(channel.get("language_confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _deepgram_segments(words: list, *, fallback_text: str) -> list[dict]:
    if not words:
        return [{"start": 0.0, "end": 0.0, "text": fallback_text}] if fallback_text else []
    text = " ".join(str(item.get("word") or "").strip() for item in words if isinstance(item, dict)).strip()
    start = float(words[0].get("start") or 0.0) if isinstance(words[0], dict) else 0.0
    end = float(words[-1].get("end") or start) if isinstance(words[-1], dict) else start
    return [{"start": start, "end": end, "text": text or fallback_text}]


def _audio_content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".wav": "audio/wav",
    }.get(suffix, "application/octet-stream")


def _transcribe_with_faster_whisper(audio_path: Path, *, settings: dict, language: str = "") -> dict:
    config = {
        "model": faster_whisper_model_ref(settings),
        "model_label": faster_whisper_model_label(settings),
        "device": faster_whisper_device(settings),
        "compute_type": faster_whisper_compute_type(settings),
        "profile": transcription_profile(settings),
        "beam_size": faster_whisper_beam_size(settings),
        "data_root": str(settings.get("_data_root") or ""),
        "initial_prompt": faster_whisper_initial_prompt(),
    }
    payload = _run_faster_whisper_worker_job(str(audio_path), config=config, language=language)
    if not payload.get("ok"):
        detail = str(payload.get("detail") or "faster-whisper transcription failed.")
        if payload.get("error_type") == "ImportError":
            raise SpeechProviderUnavailableError("faster-whisper is not installed.")
        raise SpeechTranscriptionError(detail)
    return payload["result"]


def _run_faster_whisper_worker_job(audio_path: str, *, config: dict, language: str) -> dict:
    fallback_reason = ""
    if persistent_faster_whisper_worker_enabled() and config.get("data_root"):
        try:
            return _run_external_faster_whisper_worker_job(audio_path, config=config, language=language)
        except (OSError, TimeoutError, SpeechTranscriptionError) as error:
            fallback_reason = f"{error.__class__.__name__}: {error}"
            if strict_persistent_faster_whisper_worker_enabled():
                raise SpeechTranscriptionError(
                    f"faster-whisper persistent worker failed: {fallback_reason}. "
                    "Set MAVERICK_SPEECH_FASTER_WHISPER_WORKER=auto or entrypoint to allow fallback."
                ) from error
    payload = _run_entrypoint_faster_whisper_worker_job(audio_path, config=config, language=language)
    if fallback_reason and payload.get("ok") and isinstance(payload.get("result"), dict):
        worker = payload["result"].setdefault("worker", {})
        if isinstance(worker, dict):
            worker["persistent_worker_attempted"] = True
            worker["persistent_worker_fallback_reason"] = fallback_reason
    return payload


def _run_entrypoint_faster_whisper_worker_job(audio_path: str, *, config: dict, language: str) -> dict:
    with _FASTER_WHISPER_LOCK:
        worker = _ensure_faster_whisper_worker(config)
        job_id = f"fw_{uuid.uuid4().hex}"
        try:
            worker["requests"].put({"job_id": job_id, "audio_path": audio_path, "language": language}, timeout=FASTER_WHISPER_QUEUE_TIMEOUT_SECONDS)
        except queue.Full as error:
            raise SpeechTranscriptionError("faster-whisper worker queue is full.") from error
        deadline = time.monotonic() + FASTER_WHISPER_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not worker["process"].is_alive():
                _stop_faster_whisper_worker(worker)
                raise SpeechTranscriptionError("faster-whisper worker exited before returning a result.")
            try:
                payload = worker["results"].get(timeout=1)
            except queue.Empty:
                continue
            if payload.get("job_id") == job_id:
                return payload
        _stop_faster_whisper_worker(worker)
        raise SpeechTranscriptionError("faster-whisper transcription timed out.")


def faster_whisper_worker_mode() -> str:
    return os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_WORKER", "auto").strip().lower() or "auto"


def persistent_faster_whisper_worker_enabled() -> bool:
    return faster_whisper_worker_mode() not in {"0", "false", "no", "off", "entrypoint", "process", "disabled"}


def strict_persistent_faster_whisper_worker_enabled() -> bool:
    return faster_whisper_worker_mode() == "persistent"


def _run_external_faster_whisper_worker_job(audio_path: str, *, config: dict, language: str) -> dict:
    paths = _external_faster_whisper_worker_paths(config)
    _ensure_external_faster_whisper_worker(config, socket_path=paths["socket"], pid_path=paths["pid"], lock_path=paths["lock"])
    return _send_external_faster_whisper_job(
        paths["socket"],
        {
            "audio_path": audio_path,
            "language": language,
            "initial_prompt": str(config.get("initial_prompt") or ""),
        },
    )


def _external_faster_whisper_worker_paths(config: dict) -> dict[str, Path]:
    data_root = Path(str(config.get("data_root") or "")).expanduser()
    worker_config = _faster_whisper_worker_config(config)
    digest = hashlib.sha256(json.dumps(worker_config, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    run_dir = data_root / "run"
    return {
        "socket": run_dir / f"fw-{digest}.sock",
        "pid": run_dir / f"fw-{digest}.pid",
        "lock": run_dir / f"fw-{digest}.lock",
        "log": run_dir / f"fw-{digest}.log",
    }


def _ensure_external_faster_whisper_worker(config: dict, *, socket_path: Path, pid_path: Path, lock_path: Path) -> None:
    if _external_worker_accepts_connection(socket_path):
        return
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    with _locked_worker_start(lock_path):
        if _external_worker_accepts_connection(socket_path):
            return
        paths = _external_faster_whisper_worker_paths(config)
        log_path = paths["log"]
        _remove_stale_external_worker_files(socket_path, pid_path)
        worker_config = _faster_whisper_worker_config(config)
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("stt_worker.py")),
                    "--socket",
                    str(socket_path),
                    "--pid-file",
                    str(pid_path),
                    "--config-json",
                    json.dumps(worker_config, sort_keys=True),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                close_fds=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + FASTER_WHISPER_WORKER_START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if _external_worker_accepts_connection(socket_path):
                    _EXTERNAL_WORKER_PROCESSES[process.pid] = process
                    return
                if process.poll() is not None:
                    break
                time.sleep(0.1)
    raise SpeechTranscriptionError("faster-whisper persistent worker did not become ready.")


def _send_external_faster_whisper_job(socket_path: Path, request: dict) -> dict:
    deadline = time.monotonic() + FASTER_WHISPER_TIMEOUT_SECONDS
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(FASTER_WHISPER_QUEUE_TIMEOUT_SECONDS)
        client.connect(str(socket_path))
        client.sendall((json.dumps(request, sort_keys=True) + "\n").encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            client.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
            try:
                chunk = client.recv(1024 * 1024)
            except socket.timeout:
                continue
            if not chunk:
                break
            chunks.append(chunk)
    if not chunks:
        raise SpeechTranscriptionError("faster-whisper persistent worker returned an empty response.")
    return json.loads(b"".join(chunks).decode("utf-8"))


def _external_worker_accepts_connection(socket_path: Path) -> bool:
    if not socket_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(str(socket_path))
        return True
    except OSError:
        return False


def _remove_stale_external_worker_files(socket_path: Path, pid_path: Path, *, script_name: str = "stt_worker.py") -> None:
    pid = _read_worker_pid(pid_path)
    if pid and _pid_matches_worker(pid, socket_path, script_name=script_name):
        _terminate_worker_pid(pid)
    for path in (socket_path, pid_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _faster_whisper_worker_config(config: dict) -> dict:
    model = str(config.get("model") or DEFAULT_FASTER_WHISPER_MODEL)
    return {
        "model": model,
        "model_label": str(config.get("model_label") or ""),
        "model_fingerprint": _file_fingerprint(model) if _looks_like_path(model) else {"configured": False},
        "device": str(config.get("device") or DEFAULT_FASTER_WHISPER_DEVICE),
        "compute_type": str(config.get("compute_type") or DEFAULT_FASTER_WHISPER_COMPUTE_TYPE),
        "profile": str(config.get("profile") or ""),
        "beam_size": int(config.get("beam_size") or 1),
    }


def faster_whisper_worker_status(data_root: Path, settings: dict | None = None, *, ensure_warm: bool = False) -> dict:
    targets = _worker_status_targets(data_root, settings or {})
    primary = targets[0]
    _prune_stale_external_worker_files(data_root, current_paths=[target["paths"] for target in targets])
    for target in targets:
        target["prewarm"] = (
            _prewarm_external_worker_status(target["config"], target["paths"], target["settings"])
            if ensure_warm
            else {"attempted": False, "ok": False, "detail": "", "skipped_reason": "not_requested"}
        )
        target["current"] = _worker_file_status(target["paths"])
    return {
        "mode": faster_whisper_worker_mode(),
        "enabled": persistent_faster_whisper_worker_enabled(),
        "scope": "workspace_daemon" if persistent_faster_whisper_worker_enabled() else "entrypoint_process",
        "settings_profile": transcription_profile(settings),
        "current_profile": primary["profile"],
        "current_usage": primary["usages"][0]["usage"],
        "prewarm": primary["prewarm"],
        "current": primary["current"],
        "profiles": [_public_worker_status_target(target) for target in targets],
        "workers": [_worker_file_status(worker_paths) for worker_paths in _all_external_worker_paths(data_root)],
    }


def _worker_status_targets(data_root: Path, settings: dict) -> list[dict]:
    base_settings = dict(settings)
    candidates = [
        (
            "inline_default",
            "transcribe_audio",
            {**base_settings, "transcription_profile": DEFAULT_INLINE_TRANSCRIPTION_PROFILE},
            True,
        ),
        (
            "workspace_default",
            "transcribe_file",
            base_settings,
            False,
        ),
    ]
    targets: list[dict] = []
    by_worker_id: dict[str, dict] = {}
    for usage, operation, target_settings, prewarm_by_default in candidates:
        config = _faster_whisper_runtime_config(data_root, target_settings)
        paths = _external_faster_whisper_worker_paths(config)
        worker_id = paths["pid"].stem
        existing = by_worker_id.get(worker_id)
        if existing is not None:
            existing["usages"].append({"usage": usage, "operation": operation})
            existing["prewarm_by_default"] = bool(existing["prewarm_by_default"] or prewarm_by_default)
            continue
        target = {
            "profile": transcription_profile(target_settings),
            "settings": target_settings,
            "config": config,
            "paths": paths,
            "prewarm_by_default": prewarm_by_default,
            "usages": [{"usage": usage, "operation": operation}],
        }
        by_worker_id[worker_id] = target
        targets.append(target)
    return targets


def _faster_whisper_runtime_config(data_root: Path, settings: dict | None = None) -> dict:
    return {
        "model": faster_whisper_model_ref(settings),
        "model_label": faster_whisper_model_label(settings),
        "device": faster_whisper_device(settings),
        "compute_type": faster_whisper_compute_type(settings),
        "profile": transcription_profile(settings),
        "beam_size": faster_whisper_beam_size(settings),
        "data_root": str(data_root),
        "initial_prompt": faster_whisper_initial_prompt(),
    }


def _public_worker_status_target(target: dict) -> dict:
    return {
        "profile": target["profile"],
        "model": str(target["config"].get("model_label") or "local-model"),
        "beam_size": int(target["config"].get("beam_size") or 1),
        "usages": list(target["usages"]),
        "prewarm": target["prewarm"],
        "current": target["current"],
    }


def _prewarm_external_worker_status(config: dict, paths: dict[str, Path], settings: dict) -> dict:
    if not persistent_faster_whisper_worker_enabled():
        return {"attempted": False, "ok": False, "detail": "", "skipped_reason": "persistent_worker_disabled"}
    selected_engine = resolve_transcription_engine(settings)
    if selected_engine != "faster-whisper":
        return {
            "attempted": False,
            "ok": False,
            "detail": "",
            "skipped_reason": selected_engine_skip_reason(selected_engine),
        }
    try:
        _ensure_external_faster_whisper_worker(
            config,
            socket_path=paths["socket"],
            pid_path=paths["pid"],
            lock_path=paths["lock"],
        )
    except Exception as error:
        return {
            "attempted": True,
            "ok": False,
            "detail": f"{error.__class__.__name__}: {error}",
        }
    return {"attempted": True, "ok": True, "detail": "", "skipped_reason": ""}


def selected_engine_skip_reason(selected_engine: object) -> str:
    engine = str(selected_engine or "").strip().lower()
    if not engine:
        return "selected_engine_unavailable"
    normalized = re.sub(r"[^a-z0-9]+", "_", engine).strip("_")
    return f"selected_engine_{normalized or 'unavailable'}"


def _prune_stale_external_worker_files(data_root: Path, *, current_paths: list[dict[str, Path]]) -> None:
    seen: set[Path] = set()
    for paths in [*current_paths, *_all_external_worker_paths(data_root)]:
        pid_path = paths["pid"]
        if pid_path in seen:
            continue
        seen.add(pid_path)
        socket_path = paths["socket"]
        if _external_worker_accepts_connection(socket_path):
            continue
        if socket_path.exists() or pid_path.exists():
            _remove_stale_external_worker_files(socket_path, pid_path)


def stop_faster_whisper_workers(data_root: Path) -> dict:
    stopped: list[dict] = []
    for paths in _all_external_worker_paths(data_root):
        pid = _read_worker_pid(paths["pid"])
        stopped.append(
            {
                "worker_id": paths["pid"].stem,
                "pid": pid,
                "terminated": bool(pid and _pid_matches_worker(pid, paths["socket"]) and _terminate_worker_pid(pid)),
            }
        )
        _remove_stale_external_worker_files(paths["socket"], paths["pid"])
    return {"stopped": stopped, "count": len(stopped)}


def _all_external_worker_paths(data_root: Path) -> list[dict[str, Path]]:
    run_dir = data_root / "run"
    if not run_dir.exists():
        return []
    paths: list[dict[str, Path]] = []
    for pid_path in sorted(run_dir.glob("fw-*.pid")):
        stem = pid_path.stem
        paths.append(
            {
                "socket": run_dir / f"{stem}.sock",
                "pid": pid_path,
                "lock": run_dir / f"{stem}.lock",
                "log": run_dir / f"{stem}.log",
            }
        )
    return paths


def _worker_file_status(paths: dict[str, Path]) -> dict:
    pid = _read_worker_pid(paths["pid"])
    socket_path = paths["socket"]
    pid_alive = bool(pid and _pid_is_alive(pid))
    socket_reachable = _external_worker_accepts_connection(socket_path)
    return {
        "worker_id": paths["pid"].stem,
        "pid": pid,
        "pid_alive": pid_alive,
        "socket_exists": socket_path.exists(),
        "socket_reachable": socket_reachable,
        "active": bool(pid_alive and socket_reachable),
        "warm": bool(pid_alive and socket_reachable),
        "log_name": paths["log"].name,
        "log_exists": paths["log"].exists(),
    }


def _read_worker_pid(pid_path: Path) -> int:
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_matches_worker(pid: int, socket_path: Path, *, script_name: str = "stt_worker.py") -> bool:
    if not _pid_is_alive(pid):
        return False
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        cmdline = cmdline_path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="ignore")
    except OSError:
        return False
    return script_name in cmdline and str(socket_path) in cmdline


def _terminate_worker_pid(pid: int) -> bool:
    if not _pid_is_alive(pid):
        return False
    process = _EXTERNAL_WORKER_PROCESSES.pop(pid, None)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return True
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    if process is not None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    return True


class _locked_worker_start:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_locked_worker_start":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.handle is None:
            return
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        self.handle.close()


def _ensure_faster_whisper_worker(config: dict) -> dict:
    global _FASTER_WHISPER_WORKER
    key = json.dumps(config, sort_keys=True)
    if _FASTER_WHISPER_WORKER and _FASTER_WHISPER_WORKER.get("key") == key and _FASTER_WHISPER_WORKER["process"].is_alive():
        return _FASTER_WHISPER_WORKER
    if _FASTER_WHISPER_WORKER:
        _stop_faster_whisper_worker(_FASTER_WHISPER_WORKER)
    start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    context = multiprocessing.get_context(start_method)
    requests = context.Queue(maxsize=1)
    results = context.Queue()
    process = context.Process(target=_faster_whisper_worker_loop, args=(config, requests, results), daemon=True)
    process.start()
    _FASTER_WHISPER_WORKER = {"key": key, "process": process, "requests": requests, "results": results}
    return _FASTER_WHISPER_WORKER


def _stop_faster_whisper_worker(worker: dict) -> None:
    global _FASTER_WHISPER_WORKER
    process = worker.get("process")
    if process and process.is_alive():
        try:
            worker["requests"].put({"shutdown": True}, timeout=1)
        except Exception:
            pass
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
    if worker is _FASTER_WHISPER_WORKER:
        _FASTER_WHISPER_WORKER = None


def _faster_whisper_worker_loop(config: dict, request_queue: multiprocessing.Queue, result_queue: multiprocessing.Queue) -> None:
    model = None
    cold = True
    load_seconds = 0.0
    while True:
        task = request_queue.get()
        if task.get("shutdown"):
            return
        job_id = task.get("job_id")
        try:
            if model is None:
                start = time.monotonic()
                model = _load_faster_whisper_model(config)
                load_seconds = time.monotonic() - start
            result = _run_faster_whisper_with_model(
                model,
                Path(str(task.get("audio_path") or "")),
                config=config,
                language=str(task.get("language") or ""),
            )
            result["worker"] = {
                "scope": "entrypoint_process",
                "cross_request_reuse": False,
                "cold_start": cold,
                "model_load_seconds": load_seconds if cold else 0.0,
            }
            cold = False
            result_queue.put({"job_id": job_id, "ok": True, "result": result})
        except Exception as error:
            result_queue.put({"job_id": job_id, "ok": False, "error_type": error.__class__.__name__, "detail": str(error)})


def _load_faster_whisper_model(config: dict) -> object:
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
    return WhisperModel(model_name, **kwargs)


def _run_faster_whisper_in_process(audio_path: Path, *, config: dict, language: str = "") -> dict:
    model = _load_faster_whisper_model(config)
    return _run_faster_whisper_with_model(model, audio_path, config=config, language=language)


def _run_faster_whisper_with_model(model: object, audio_path: Path, *, config: dict, language: str = "") -> dict:
    try:
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language or None,
            initial_prompt=str(config.get("initial_prompt") or "") or None,
            vad_filter=True,
            beam_size=int(config.get("beam_size") or 1),
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
        "profile": str(config.get("profile") or ""),
        "beam_size": int(config.get("beam_size") or 1),
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
