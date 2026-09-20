"""Bounded, lifecycle-owned processes for opt-in sequential app JSON workers."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
from threading import Condition, Thread
import time
from typing import Any
from uuid import uuid4

from core.shared.entrypoints import JSON_WORKER_MESSAGE_MAX_BYTES as MAX_MESSAGE_BYTES
from core.shared.entrypoints import EntrypointInterruptedError, _kill_process_tree, _terminate_process_tree_and_wait
from core.shared.repository import installation_paths


@dataclass(eq=False)
class _Worker:
    key: tuple
    process: subprocess.Popen
    busy: bool = True
    last_used: float = 0


class JsonWorkerPool:
    """Eight processes per host, four per identity, with one idle deadline owner."""

    def __init__(self, owner, *, maximum: int = 8, per_identity: int = 4, idle_seconds: float = 180):
        self.owner = owner
        self.maximum, self.per_identity, self.idle_seconds = maximum, per_identity, idle_seconds
        self._condition = Condition()
        self._workers: list[_Worker] = []
        self._closed = False
        self._reaper: Thread | None = None

    def invoke(self, path: Path, *, cwd: Path, identity: tuple, payload: dict[str, Any], timeout_seconds: float, controller) -> dict:
        deadline = time.monotonic() + timeout_seconds
        signature = path.stat()
        key = (str(path.resolve()), str(cwd.resolve()), identity, signature.st_dev, signature.st_ino,
               signature.st_size, signature.st_mtime_ns, signature.st_ctime_ns)
        request_id = uuid4().hex
        raw = json.dumps({"request_id": request_id, "payload": payload}, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ValueError("JSON worker request exceeds its framing limit.")
        wake = lambda: self.wake()
        controller.register_cleanup(wake)
        try:
            worker = self._acquire(key, path=path, cwd=cwd, deadline=deadline, controller=controller)
        finally:
            controller.unregister_cleanup(wake)
        reusable = False
        controller.register(worker.process)
        try:
            result = _exchange(worker.process, raw, request_id=request_id, deadline=deadline)
            if controller.is_shutting_down():
                raise EntrypointInterruptedError(path, reason=controller.interruption_reason() or "shutdown")
            reusable = True
            return result
        except Exception as error:
            if controller.is_shutting_down():
                raise EntrypointInterruptedError(path, reason=controller.interruption_reason() or "shutdown") from error
            raise
        finally:
            controller.unregister(worker.process)
            with self._condition:
                worker.busy = False
                worker.last_used = time.monotonic()
                if not reusable or self._closed or worker.process.poll() is not None:
                    if worker in self._workers:
                        self._workers.remove(worker)
                    reusable = False
                self._condition.notify_all()
            if not reusable:
                _close_process(worker.process)

    def _acquire(self, key: tuple, *, path: Path, cwd: Path, deadline: float, controller) -> _Worker:
        with self._condition:
            while True:
                if self._closed or controller.is_shutting_down():
                    raise EntrypointInterruptedError(path, reason=controller.interruption_reason() or "host shutdown")
                for worker in list(self._workers):
                    if not worker.busy and worker.process.poll() is not None:
                        self._workers.remove(worker)
                        _close_process(worker.process)
                    elif worker.key == key and not worker.busy:
                        worker.busy = True
                        return worker
                matching = sum(worker.key == key for worker in self._workers)
                if len(self._workers) >= self.maximum and matching < self.per_identity:
                    idle = [worker for worker in self._workers if not worker.busy]
                    if idle:
                        oldest = min(idle, key=lambda worker: worker.last_used)
                        self._workers.remove(oldest)
                        _close_process(oldest.process)
                if len(self._workers) < self.maximum and matching < self.per_identity:
                    worker = _Worker(key, _start_process(path, cwd))
                    self._workers.append(worker)
                    if self._reaper is None:
                        self._reaper = Thread(target=self._reap, name="maverick-app-json-idle", daemon=True)
                        self._reaper.start()
                    return worker
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("App JSON worker capacity wait timed out.")
                # Host shutdown notifies immediately; request cancellation also wakes
                # through its cleanup callback, registered by the caller.
                self._condition.wait(remaining)

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            workers, self._workers = self._workers, []
            self._condition.notify_all()
        for worker in workers:
            if worker.busy:
                _terminate_process_tree_and_wait(worker.process)
            else:
                _close_process(worker.process)

    def _reap(self) -> None:
        with self._condition:
            while not self._closed:
                if not self._workers:
                    self._reaper = None
                    return
                idle = [worker for worker in self._workers if not worker.busy]
                if not idle:
                    self._condition.wait()
                    continue
                oldest = min(idle, key=lambda worker: worker.last_used)
                remaining = oldest.last_used + self.idle_seconds - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                self._workers.remove(oldest)
                _close_process(oldest.process)
                self._condition.notify_all()


def _start_process(path: Path, cwd: Path) -> subprocess.Popen:
    env = dict(os.environ)
    root = str(installation_paths(start_path=cwd).repository_root)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (root, env.get("PYTHONPATH"))))
    process = subprocess.Popen([sys.executable, "-u", str(path)], cwd=str(cwd), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    for stream in (process.stdin, process.stdout, process.stderr):
        os.set_blocking(stream.fileno(), False)
    return process


def _close_process(process: subprocess.Popen) -> None:
    _terminate_process_tree_and_wait(process)
    # A crashed leader may leave children alive in its dedicated process group.
    _kill_process_tree(process)
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _exchange(process: subprocess.Popen, raw: bytes, *, request_id: str, deadline: float) -> dict:
    """Bound input/output and duration, draining stderr without retaining secrets."""
    output = bytearray()
    sent = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdin, selectors.EVENT_WRITE, "input")
        selector.register(process.stdout, selectors.EVENT_READ, "output")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("App JSON worker request timed out.")
            for event, _mask in selector.select(remaining):
                if event.data == "input":
                    sent += os.write(event.fd, raw[sent:sent + 65536])
                    if sent == len(raw):
                        selector.unregister(process.stdin)
                    continue
                chunk = os.read(event.fd, 65536)
                if not chunk:
                    if event.data == "output":
                        raise RuntimeError("App JSON worker exited without a complete response.")
                    selector.unregister(event.fileobj)
                    continue
                if event.data != "output":
                    continue
                output.extend(chunk)
                if len(output) > MAX_MESSAGE_BYTES:
                    raise RuntimeError("App JSON worker response exceeds its framing limit.")
                if b"\n" not in chunk:
                    continue
                if not output.endswith(b"\n") or output.count(b"\n") != 1 or sent != len(raw):
                    raise RuntimeError("App JSON worker emitted invalid response framing.")
                try:
                    result = json.loads(output)
                except (ValueError, UnicodeError) as error:
                    raise RuntimeError("App JSON worker did not emit valid JSON.") from error
                if not isinstance(result, dict) or result.get("request_id") != request_id or not isinstance(result.get("result"), dict):
                    raise RuntimeError("App JSON worker emitted an invalid response identity or result.")
                return result["result"]
