"""Shared lifecycle helpers for ASGI WebSocket wait tasks."""

from __future__ import annotations

import asyncio
from typing import Any


async def cancel_websocket_tasks(*tasks: asyncio.Task[Any] | None) -> None:
    """Cancel and drain WebSocket tasks that remain active during teardown."""
    tracked_tasks = [task for task in tasks if task is not None]
    for task in tracked_tasks:
        if not task.done():
            task.cancel()
    if tracked_tasks:
        await asyncio.gather(*tracked_tasks, return_exceptions=True)
