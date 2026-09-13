"""Private WebSocket transport between Maverick Core and MaverickMac."""

from __future__ import annotations

import asyncio
import json
import queue

from core.api.websocket_tasks import cancel_websocket_tasks
from core.device_use.errors import DeviceUseError
from core.device_use.service import DeviceUseService
from core.shared.entrypoints import EntrypointShutdownController


DEVICE_USE_EXECUTOR_WS_PATH = "/ws/device-use/executor"
# A direct v40 EventKit read can contain just under 200 KB of JSON. Encoding
# that JSON string in the result envelope may escape it close to twice, so the
# transport needs a larger—but still fixed—control-frame ceiling.
MAX_DEVICE_CONTROL_FRAME_BYTES = 512_000


async def stream_device_use_executor(
    *,
    service: DeviceUseService,
    scope: dict,
    receive,
    send,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> None:
    """Redeem one ticket and relay bounded native executor frames."""
    if str(scope.get("path") or "") != DEVICE_USE_EXECUTOR_WS_PATH:
        await send({"type": "websocket.close", "code": 4404})
        return
    ticket = _bearer_token(scope)
    try:
        activation_id = service.activation_id_for_ticket(ticket)
    except DeviceUseError:
        await send({"type": "websocket.close", "code": 4401})
        return
    first = await receive()
    if first.get("type") != "websocket.connect":
        await send({"type": "websocket.close", "code": 4408})
        return
    await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
    outbound: queue.Queue[dict[str, object] | None] = queue.Queue(maxsize=8)
    sender_task: asyncio.Task | None = None
    shutdown_task: asyncio.Task | None = None
    heartbeat_task: asyncio.Task | None = None
    connected = False
    try:
        hello_message = await asyncio.wait_for(receive(), timeout=10.0)
        hello = _json_message(hello_message)
        if hello.get("type") != "device_use.hello.v1":
            raise ValueError("device_use_hello_required")
        ready = service.connect_executor(
            ticket=ticket,
            protocol_version=str(hello.get("protocol_version") or ""),
            executor_contract=str(hello.get("executor_contract") or ""),
            tool_contract_digest=str(hello.get("tool_contract_digest") or ""),
            initial_app=str(hello.get("initial_app") or ""),
            approved_apps=(
                hello.get("approved_apps")
                if isinstance(hello.get("approved_apps"), list)
                else []
            ),
            outbound=outbound,
        )
        connected = True
        await _send_json(send, {"type": "device_use.ready.v1", **ready})
        sender_task = asyncio.create_task(_send_outbound(outbound, send))
        heartbeat_task = asyncio.create_task(_queue_heartbeats(outbound))
        shutdown_task = _shutdown_task(shutdown_controller)
        while True:
            receive_task = asyncio.create_task(receive())
            watched = {receive_task}
            if sender_task is not None:
                watched.add(sender_task)
            if shutdown_task is not None:
                watched.add(shutdown_task)
            done, _pending = await asyncio.wait(
                watched,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receive_task not in done:
                receive_task.cancel()
                await asyncio.gather(receive_task, return_exceptions=True)
            if shutdown_task is not None and shutdown_task in done:
                return
            if sender_task is not None and sender_task in done:
                return
            if receive_task not in done:
                continue
            incoming = receive_task.result()
            if incoming.get("type") == "websocket.disconnect":
                return
            if incoming.get("bytes") is not None:
                payload = incoming.get("bytes")
                if not isinstance(payload, bytes):
                    raise ValueError("device_use_binary_frame_invalid")
                service.deliver_image(activation_id, payload)
                continue
            frame = _json_message(incoming)
            frame_type = frame.get("type")
            if frame_type == "device_use.accepted.v1":
                service.accept_invocation(activation_id, frame)
            elif frame_type == "device_use.result.v1":
                service.deliver_result(activation_id, frame)
            elif frame_type == "device_use.heartbeat.v1":
                continue
            elif frame_type == "device_use.stopped.v1":
                service.stop_activation(activation_id, reason="stopped_by_device")
                return
            else:
                raise ValueError("device_use_frame_not_allowed")
    except (DeviceUseError, ValueError, asyncio.TimeoutError):
        if connected:
            service.stop_activation(activation_id, reason="device_use_protocol_failure")
        await send({"type": "websocket.close", "code": 4408})
    finally:
        if connected:
            service.disconnect_executor(activation_id)
        # asyncio.to_thread(queue.get) cannot be cancelled while blocked. Wake
        # that worker explicitly so a closed native socket never leaks a thread.
        while True:
            try:
                outbound.get_nowait()
            except queue.Empty:
                break
        outbound.put_nowait(None)
        await cancel_websocket_tasks(sender_task, heartbeat_task, shutdown_task)


async def _send_outbound(
    outbound: queue.Queue[dict[str, object] | None], send
) -> None:
    while True:
        frame = await asyncio.to_thread(outbound.get)
        if frame is None:
            return
        await _send_json(send, frame)


async def _queue_heartbeats(
    outbound: queue.Queue[dict[str, object] | None],
    interval_seconds: float = 20.0,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            outbound.put_nowait({"type": "device_use.heartbeat.v1"})
        except queue.Full:
            # A full single-device queue is itself backpressure; do not evict work.
            continue


def _json_message(message: dict) -> dict[str, object]:
    text = message.get("text")
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > MAX_DEVICE_CONTROL_FRAME_BYTES:
        raise ValueError("device_use_control_frame_invalid")
    try:
        payload = json.loads(
            text,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("device_use_control_frame_invalid")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("device_use_control_frame_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("device_use_control_frame_invalid")
    return payload


async def _send_json(send, frame: dict[str, object]) -> None:
    encoded = json.dumps(
        frame,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )
    if len(encoded.encode("utf-8")) > MAX_DEVICE_CONTROL_FRAME_BYTES:
        raise ValueError("device_use_control_frame_invalid")
    await send(
        {
            "type": "websocket.send",
            "text": encoded,
        }
    )


def _bearer_token(scope: dict) -> str:
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin1").lower()
        if name != "authorization":
            continue
        value = raw_value.decode("latin1")
        if value.lower().startswith("bearer "):
            return value[7:].strip()
    return ""


def _shutdown_task(
    controller: EntrypointShutdownController | None,
) -> asyncio.Task | None:
    if controller is None:
        return None
    return asyncio.create_task(_wait_for_shutdown(controller))


async def _wait_for_shutdown(controller: EntrypointShutdownController) -> None:
    while not controller.is_shutting_down():
        await asyncio.sleep(0.1)


def _json_default(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
