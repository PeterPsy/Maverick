"""Workspace app data-change event stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from core.shared.entrypoints import EntrypointShutdownController


APP_EVENTS_WS_PATH = "/api/apps/events/ws"


class AppEventBus:
    """In-memory fanout bus for live app UI updates."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)


async def stream_app_events(
    *,
    bus: AppEventBus,
    scope: dict[str, Any],
    receive,
    send,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> None:
    """Stream app events over a WebSocket without client polling."""
    if str(scope.get("path") or "") != APP_EVENTS_WS_PATH:
        await send({"type": "websocket.close", "code": 4404})
        return
    await send({"type": "websocket.accept"})
    queue = bus.subscribe()
    try:
        while True:
            event_task = asyncio.create_task(queue.get())
            receive_task = asyncio.create_task(receive())
            shutdown_task = _shutdown_task(shutdown_controller)
            wait_tasks = {event_task, receive_task}
            if shutdown_task is not None:
                wait_tasks.add(shutdown_task)
            done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            if shutdown_task is not None and shutdown_task in done:
                return
            if receive_task in done:
                message = receive_task.result()
                if message.get("type") == "websocket.disconnect":
                    return
            if event_task in done:
                await send({"type": "websocket.send", "text": json.dumps(event_task.result(), ensure_ascii=False)})
    finally:
        bus.unsubscribe(queue)


def _shutdown_task(shutdown_controller: EntrypointShutdownController | None) -> asyncio.Task | None:
    if shutdown_controller is None:
        return None
    return asyncio.create_task(_wait_for_shutdown(shutdown_controller))


async def _wait_for_shutdown(shutdown_controller: EntrypointShutdownController) -> None:
    while not shutdown_controller.is_shutting_down():
        await asyncio.sleep(0.1)
