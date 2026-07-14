#!/usr/bin/env python3
"""Benchmark OpenRouter Kokoro first-byte and full-stream latency."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from kokoro_streaming import KokoroConnectionPool, open_kokoro_openrouter_stream


DEFAULT_LENGTHS = (40, 80, 120, 450)
DEFAULT_FORMATS = ("mp3", "pcm")
DEFAULT_CONNECTION_MODES = ("fresh", "pooled")


def main() -> int:
    args = parse_args()
    cases = benchmark_cases(
        lengths=comma_separated_ints(args.lengths),
        formats=comma_separated_values(args.formats),
        connection_modes=comma_separated_values(args.connection_modes),
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "endpoint": "https://openrouter.ai/api/v1/audio/speech",
                    "model": "hexgrad/kokoro-82m",
                    "request_count": args.requests,
                    "interval_seconds": args.interval_seconds,
                    "cases": cases,
                },
                indent=2,
            )
        )
        return 0
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("OPENROUTER_API_KEY is required unless --dry-run is used.", file=sys.stderr)
        return 2
    results = run_benchmark(
        cases=cases,
        request_count=max(1, args.requests),
        interval_seconds=max(0.0, args.interval_seconds),
        api_key=api_key,
        voice=args.voice,
    )
    payload = {
        "request_count": len(results),
        "success_count": sum(1 for result in results if result.get("ok")),
        "error_count": sum(1 for result in results if not result.get("ok")),
        "summaries": summarize_results(results),
        "results": results if args.include_requests else None,
    }
    if payload["results"] is None:
        payload.pop("results")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["success_count"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=100, help="Total requests distributed round-robin across cases.")
    parser.add_argument("--interval-seconds", type=float, default=0.25, help="Delay between requests.")
    parser.add_argument("--lengths", default=",".join(str(value) for value in DEFAULT_LENGTHS))
    parser.add_argument("--formats", default=",".join(DEFAULT_FORMATS))
    parser.add_argument("--connection-modes", default=",".join(DEFAULT_CONNECTION_MODES))
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--include-requests", action="store_true", help="Include every request record in JSON output.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def benchmark_cases(*, lengths: list[int], formats: list[str], connection_modes: list[str]) -> list[dict]:
    invalid_formats = sorted(set(formats) - {"mp3", "pcm"})
    invalid_modes = sorted(set(connection_modes) - {"fresh", "pooled"})
    if invalid_formats:
        raise ValueError(f"Unsupported formats: {', '.join(invalid_formats)}")
    if invalid_modes:
        raise ValueError(f"Unsupported connection modes: {', '.join(invalid_modes)}")
    return [
        {"text_chars": length, "format": response_format, "connection_mode": connection_mode}
        for length in lengths
        if length > 0
        for response_format in formats
        for connection_mode in connection_modes
    ]


def run_benchmark(
    *,
    cases: list[dict],
    request_count: int,
    interval_seconds: float,
    api_key: str,
    voice: str,
) -> list[dict]:
    if not cases:
        raise ValueError("At least one benchmark case is required.")
    pooled = KokoroConnectionPool()
    results: list[dict] = []
    try:
        for request_index in range(request_count):
            case = cases[request_index % len(cases)]
            pool = pooled if case["connection_mode"] == "pooled" else KokoroConnectionPool()
            started = time.monotonic()
            try:
                stream = open_kokoro_openrouter_stream(
                    text=benchmark_text(int(case["text_chars"])),
                    voice=voice,
                    settings={"_app_secrets": {"openrouter-api-key": api_key}},
                    response_format=str(case["format"]),
                    pool=pool,
                )
                size_bytes = sum(len(chunk) for chunk in stream.iter_chunks())
                result = {
                    **case,
                    "request_index": request_index,
                    "ok": True,
                    "size_bytes": size_bytes,
                    "generation_id": stream.generation_id,
                    "connection_reused": stream.connection_reused,
                    **stream.timings,
                    "request_total_ms": round((time.monotonic() - started) * 1000, 3),
                }
            except Exception as error:
                result = {
                    **case,
                    "request_index": request_index,
                    "ok": False,
                    "error_type": error.__class__.__name__,
                    "detail": str(error),
                    "request_total_ms": round((time.monotonic() - started) * 1000, 3),
                }
            finally:
                if case["connection_mode"] == "fresh":
                    pool.close()
            results.append(result)
            if interval_seconds and request_index + 1 < request_count:
                time.sleep(interval_seconds)
    finally:
        pooled.close()
    return results


def summarize_results(results: list[dict]) -> list[dict]:
    groups: dict[tuple[int, str, str], list[dict]] = {}
    for result in results:
        key = (int(result["text_chars"]), str(result["format"]), str(result["connection_mode"]))
        groups.setdefault(key, []).append(result)
    summaries: list[dict] = []
    for (text_chars, response_format, connection_mode), group in sorted(groups.items()):
        successful = [result for result in group if result.get("ok")]
        summary = {
            "text_chars": text_chars,
            "format": response_format,
            "connection_mode": connection_mode,
            "requests": len(group),
            "successes": len(successful),
            "errors": len(group) - len(successful),
        }
        for metric in ("upstream_connect_ms", "upstream_headers_ms", "upstream_first_audio_byte_ms", "upstream_last_audio_byte_ms", "request_total_ms"):
            values = [float(result[metric]) for result in successful if metric in result]
            if values:
                summary[f"{metric}_p50"] = percentile(values, 0.5)
                summary[f"{metric}_p90"] = percentile(values, 0.9)
        summaries.append(summary)
    return summaries


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * quantile)
    return round(ordered[index], 3)


def benchmark_text(length: int) -> str:
    seed = "Maverick measures Kokoro streaming latency with a stable sentence. "
    return (seed * ((length // len(seed)) + 1))[:length]


def comma_separated_values(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def comma_separated_ints(value: str) -> list[int]:
    return [int(item) for item in comma_separated_values(value)]


if __name__ == "__main__":
    raise SystemExit(main())
