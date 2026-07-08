"""Startup performance instrumentation helpers.

The instrumentation is intentionally opt-in so normal development logs do not
become noisy. Set ``MAVERICK_STARTUP_PERF_LOGS=1`` to emit structured timing
records while collecting startup baselines.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
import time
from typing import Iterator, Mapping


logger = logging.getLogger("maverick.startup")

_ENABLED_VALUES = {"1", "true", "yes", "on", "debug"}


def startup_performance_enabled() -> bool:
    """Return whether startup performance logs should be emitted."""
    return os.environ.get("MAVERICK_STARTUP_PERF_LOGS", "").strip().lower() in _ENABLED_VALUES


@dataclass(frozen=True)
class StartupTiming:
    """One measured startup operation."""

    name: str
    duration_ms: float
    payload: Mapping[str, object]


def record_startup_timing(name: str, *, duration_ms: float, **payload: object) -> StartupTiming:
    """Emit one structured startup timing record when instrumentation is enabled."""
    timing = StartupTiming(name=name, duration_ms=round(max(duration_ms, 0.0), 3), payload=dict(payload))
    if startup_performance_enabled():
        logger.info(
            "startup.performance %s",
            json.dumps(
                {
                    "type": "startup.performance",
                    "name": timing.name,
                    "duration_ms": timing.duration_ms,
                    "at": datetime.now(tz=UTC).isoformat(),
                    **timing.payload,
                },
                default=str,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    return timing


@contextmanager
def startup_timer(name: str, **payload: object) -> Iterator[dict[str, object]]:
    """Measure a block and emit the timing with mutable payload details."""
    details: dict[str, object] = dict(payload)
    started_at = time.perf_counter()
    try:
        yield details
    finally:
        record_startup_timing(name, duration_ms=(time.perf_counter() - started_at) * 1000, **details)
