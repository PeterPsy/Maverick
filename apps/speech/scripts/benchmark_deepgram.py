#!/usr/bin/env python3
"""Benchmark Deepgram Nova and Flux profiles for Speech."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from flux_streaming import FluxWebSocketClient  # noqa: E402

DEFAULT_PRERECORDED_MODELS = ("nova-2", "nova-3")
DEFAULT_FLUX_MODEL = "flux-general-multi"


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(json.dumps(dry_run_payload(args), indent=2, sort_keys=True))
        return 0
    audio_path = Path(args.audio or "").expanduser()
    if not audio_path.is_file():
        print(json.dumps({"error": "audio_file_required", "detail": "--audio must point to a readable audio file."}), file=sys.stderr)
        return 2
    api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"error": "deepgram_api_key_required", "detail": "Set DEEPGRAM_API_KEY in the environment."}), file=sys.stderr)
        return 2
    result = run_benchmark(
        audio_path=audio_path,
        api_key=api_key,
        language=args.language,
        prerecorded_models=tuple(args.prerecorded_model),
        flux_model=args.flux_model,
        flux_chunk_bytes=args.flux_chunk_bytes,
        interrupt_after_chunks=args.interrupt_after_chunks,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Deepgram Nova prerecorded and Flux realtime profiles.")
    parser.add_argument("--audio", help="Audio file to send to Deepgram.")
    parser.add_argument("--language", default="", help="Optional language hint such as en or it.")
    parser.add_argument(
        "--prerecorded-model",
        action="append",
        default=list(DEFAULT_PRERECORDED_MODELS),
        help="Prerecorded model to test. May be repeated.",
    )
    parser.add_argument("--flux-model", default=DEFAULT_FLUX_MODEL, help="Flux model to test.")
    parser.add_argument("--flux-chunk-bytes", type=int, default=32_768, help="Bytes per Flux send chunk.")
    parser.add_argument(
        "--interrupt-after-chunks",
        type=int,
        default=0,
        help="Close the Flux stream after this many chunks to measure early interruption behavior.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the benchmark plan without network calls.")
    return parser.parse_args()


def dry_run_payload(args: argparse.Namespace) -> dict[str, object]:
    return {
        "mode": "dry_run",
        "prerecorded": [
            {
                "model": model,
                "endpoint": f"https://api.deepgram.com/v1/listen?model={model}",
                "metrics": ["http_latency_seconds", "duration_seconds", "transcript_chars"],
            }
            for model in args.prerecorded_model
        ],
        "flux": {
            "model": args.flux_model,
            "endpoint": f"wss://api.deepgram.com/v2/listen?model={args.flux_model}",
            "metrics": ["time_to_first_partial_seconds", "end_of_turn_latency_seconds", "interruption_close_latency_seconds"],
        },
    }


def run_benchmark(
    *,
    audio_path: Path,
    api_key: str,
    language: str,
    prerecorded_models: tuple[str, ...],
    flux_model: str,
    flux_chunk_bytes: int,
    interrupt_after_chunks: int,
) -> dict[str, object]:
    audio = audio_path.read_bytes()
    return {
        "audio": {"path": str(audio_path), "size_bytes": len(audio)},
        "prerecorded": [
            benchmark_prerecorded(audio=audio, api_key=api_key, model=model, language=language, content_type=content_type_for_path(audio_path))
            for model in prerecorded_models
        ],
        "flux": benchmark_flux(
            audio=audio,
            api_key=api_key,
            model=flux_model,
            language=language,
            chunk_bytes=max(1, flux_chunk_bytes),
            interrupt_after_chunks=max(0, interrupt_after_chunks),
        ),
    }


def benchmark_prerecorded(*, audio: bytes, api_key: str, model: str, language: str, content_type: str) -> dict[str, object]:
    query = f"model={model}&smart_format=true&punctuate=true"
    query += f"&language={language}" if language else "&detect_language=true"
    request = urllib_request.Request(
        f"https://api.deepgram.com/v1/listen?{query}",
        data=audio,
        headers={"Authorization": f"Token {api_key}", "Content-Type": content_type},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib_request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        return {"model": model, "ok": False, "error": f"http_{error.code}"}
    except Exception as error:
        return {"model": model, "ok": False, "error": type(error).__name__}
    elapsed = time.monotonic() - started
    transcript = best_transcript(payload)
    duration = payload.get("metadata", {}).get("duration") if isinstance(payload.get("metadata"), dict) else None
    return {
        "model": model,
        "ok": True,
        "http_latency_seconds": round(elapsed, 6),
        "duration_seconds": duration,
        "transcript_chars": len(transcript),
    }


def benchmark_flux(
    *,
    audio: bytes,
    api_key: str,
    model: str,
    language: str,
    chunk_bytes: int,
    interrupt_after_chunks: int,
) -> dict[str, object]:
    query = f"model={model}" + (f"&language={language}" if language else "")
    client = FluxWebSocketClient(f"wss://api.deepgram.com/v2/listen?{query}", headers={"Authorization": f"Token {api_key}"}, timeout=120)
    started = time.monotonic()
    first_partial_at = None
    end_of_turn_at = None
    close_started_at = None
    chunks_sent = 0
    try:
        client.connect()
        for offset in range(0, len(audio), chunk_bytes):
            chunks_sent += 1
            client.send_binary(audio[offset : offset + chunk_bytes])
            event = drain_one_event(client)
            if event and event_text(event) and first_partial_at is None:
                first_partial_at = time.monotonic()
            if interrupt_after_chunks and chunks_sent >= interrupt_after_chunks:
                break
        close_started_at = time.monotonic()
        client.send_json({"type": "CloseStream"})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            event = drain_one_event(client)
            if event is None:
                break
            if event_text(event) and first_partial_at is None:
                first_partial_at = time.monotonic()
            if str(event.get("type") or "") == "EndOfTurn":
                end_of_turn_at = time.monotonic()
                break
    except Exception as error:
        return {"model": model, "ok": False, "error": type(error).__name__, "chunks_sent": chunks_sent}
    finally:
        client.close()
    return {
        "model": model,
        "ok": True,
        "chunks_sent": chunks_sent,
        "time_to_first_partial_seconds": None if first_partial_at is None else round(first_partial_at - started, 6),
        "end_of_turn_latency_seconds": None if end_of_turn_at is None or close_started_at is None else round(end_of_turn_at - close_started_at, 6),
        "interruption_close_latency_seconds": None if close_started_at is None else round(time.monotonic() - close_started_at, 6),
        "interrupted": bool(interrupt_after_chunks),
    }


def drain_one_event(client: FluxWebSocketClient) -> dict[str, object] | None:
    try:
        return client.receive_json(0.25)
    except TimeoutError:
        return None


def best_transcript(payload: dict[str, object]) -> str:
    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
    channels = results.get("channels") if isinstance(results, dict) else []
    if not isinstance(channels, list) or not channels or not isinstance(channels[0], dict):
        return ""
    alternatives = channels[0].get("alternatives")
    if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], dict):
        return ""
    return str(alternatives[0].get("transcript") or "")


def event_text(event: dict[str, object]) -> str:
    text = str(event.get("transcript") or event.get("text") or "").strip()
    if text:
        return text
    channel = event.get("channel") if isinstance(event.get("channel"), dict) else {}
    alternatives = channel.get("alternatives") if isinstance(channel, dict) else None
    if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], dict):
        return str(alternatives[0].get("transcript") or "").strip()
    return ""


def content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".flac": "audio/flac",
        ".m4a": "audio/m4a",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
    }.get(suffix, "application/octet-stream")


if __name__ == "__main__":
    raise SystemExit(main())
