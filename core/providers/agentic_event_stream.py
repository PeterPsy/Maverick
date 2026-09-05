"""Deterministic cleanup of provider event iterators at consumption boundaries."""

from contextlib import asynccontextmanager


@asynccontextmanager
async def closing_runtime_events(events):
    """Close generators on consumer failure, without requiring it of iterators."""
    try:
        yield events
    finally:
        close = getattr(events, "aclose", None)
        if callable(close):
            await close()


__all__ = ["closing_runtime_events"]
