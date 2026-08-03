"""Authenticated Unix-to-loopback relay worker for confined HTTP sidecars.

This module intentionally depends only on the Python standard library because
the launcher mounts this single file into the sidecar sandbox.
"""

from __future__ import annotations

import argparse
import hmac
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
from threading import BoundedSemaphore, Event, Thread
import time


RELAY_PROTOCOL_PREFIX = b"MAVERICK-SIDECAR-RELAY/1 "
_MAX_PREAMBLE_BYTES = 256
_CONNECT_TIMEOUT_SECONDS = 2.0


def _read_relay_secret(fd: int) -> bytes:
    try:
        value = os.read(fd, _MAX_PREAMBLE_BYTES).strip()
    finally:
        os.close(fd)
    if not 32 <= len(value) <= 128 or any(byte < 33 or byte > 126 for byte in value):
        raise RuntimeError("invalid sidecar relay capability")
    return value


def _read_preamble(client: socket.socket) -> tuple[bytes, bytes]:
    received = b""
    while b"\n" not in received:
        chunk = client.recv(_MAX_PREAMBLE_BYTES - len(received))
        if not chunk:
            return received, b""
        received += chunk
        if len(received) >= _MAX_PREAMBLE_BYTES:
            break
    line, separator, remainder = received.partition(b"\n")
    return line + separator, remainder


def _copy_stream(source: socket.socket, destination: socket.socket, *, initial: bytes = b"") -> None:
    try:
        if initial:
            destination.sendall(initial)
        while True:
            chunk = source.recv(64 * 1024)
            if not chunk:
                break
            destination.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _serve_connection(
    client: socket.socket,
    *,
    capability: bytes,
    target_host: str,
    target_port: int,
    request_slots: BoundedSemaphore,
) -> None:
    upstream: socket.socket | None = None
    try:
        client.settimeout(_CONNECT_TIMEOUT_SECONDS)
        preamble, remainder = _read_preamble(client)
        expected = RELAY_PROTOCOL_PREFIX + capability + b"\n"
        if not hmac.compare_digest(preamble, expected):
            return
        upstream = socket.create_connection((target_host, target_port), timeout=_CONNECT_TIMEOUT_SECONDS)
        client.settimeout(None)
        upstream.settimeout(None)
        request_thread = Thread(
            target=_copy_stream,
            args=(client, upstream),
            kwargs={"initial": remainder},
            daemon=True,
        )
        request_thread.start()
        _copy_stream(upstream, client)
        request_thread.join(timeout=1)
    except OSError:
        return
    finally:
        client.close()
        if upstream is not None:
            upstream.close()
        request_slots.release()


def _serve_relay(
    listener: socket.socket,
    *,
    stop: Event,
    capability: bytes,
    target_host: str,
    target_port: int,
    request_concurrency: int,
) -> None:
    request_slots = BoundedSemaphore(request_concurrency)
    listener.settimeout(0.25)
    while not stop.is_set():
        try:
            client, _address = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        if not request_slots.acquire(blocking=False):
            client.close()
            continue
        Thread(
            target=_serve_connection,
            args=(client,),
            kwargs={
                "capability": capability,
                "target_host": target_host,
                "target_port": target_port,
                "request_slots": request_slots,
            },
            daemon=True,
        ).start()


def _apply_resource_limits(*, memory_bytes: int, open_files: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (open_files, open_files))


def run_relay_worker(args: argparse.Namespace) -> int:
    if args.request_concurrency <= 0:
        raise RuntimeError("sidecar relay request concurrency must be positive")
    capability = _read_relay_secret(args.secret_fd)
    relay_path = Path(args.relay_socket)
    if relay_path.exists() or relay_path.is_symlink():
        raise RuntimeError("sidecar relay socket already exists")
    if not relay_path.parent.is_dir() or relay_path.parent.is_symlink():
        raise RuntimeError("sidecar relay directory is unavailable")

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stop = Event()
    child: subprocess.Popen[bytes] | None = None
    try:
        listener.bind(str(relay_path))
        os.chmod(relay_path, 0o600)
        listener.listen(64)
        _apply_resource_limits(memory_bytes=args.memory_bytes, open_files=args.open_files)
        relay_thread = Thread(
            target=_serve_relay,
            args=(listener,),
            kwargs={
                "stop": stop,
                "capability": capability,
                "target_host": args.target_host,
                "target_port": args.target_port,
                "request_concurrency": args.request_concurrency,
            },
            daemon=True,
        )
        relay_thread.start()
        child = subprocess.Popen(
            args.command,
            cwd=args.workdir,
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )

        def terminate_child(_signum: int, _frame: object) -> None:
            stop.set()
            if child is not None and child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGTERM, terminate_child)
        signal.signal(signal.SIGINT, terminate_child)
        return child.wait()
    finally:
        stop.set()
        listener.close()
        if child is not None and child.poll() is None:
            child.terminate()
            deadline = time.monotonic() + 2
            while child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if child.poll() is None:
                child.kill()
            child.wait()
        relay_path.unlink(missing_ok=True)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one confined sidecar relay and daemon.")
    parser.add_argument("--relay-socket", required=True)
    parser.add_argument("--secret-fd", type=int, required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--open-files", type=int, required=True)
    parser.add_argument("--request-concurrency", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main() -> None:
    args = _argument_parser().parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        raise SystemExit("sidecar command is required")
    try:
        status = run_relay_worker(args)
    except Exception as error:
        print(f"confined sidecar relay failed: {error}", file=sys.stderr)
        raise SystemExit(125) from error
    raise SystemExit(status)


if __name__ == "__main__":
    main()
