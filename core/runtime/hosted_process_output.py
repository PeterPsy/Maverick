"""Bounded output capture and timeout enforcement for hosted tool processes."""

from __future__ import annotations

import os
import selectors
import subprocess
from threading import Event, Lock, Thread
import time

from core.runtime.hosted_process_termination import terminate_hosted_process


MAX_PROCESS_OUTPUT_BYTES = 16_777_216


class HostedProcessOutputCapture:
    """Drain a child pipe into one bounded private file until exit or timeout."""

    def __init__(
        self,
        *,
        process: subprocess.Popen[bytes],
        output_handle,
        timeout_seconds: int,
    ) -> None:
        self.process = process
        self.output_handle = output_handle
        self.timeout_seconds = timeout_seconds
        self._finished = Event()
        self._lock = Lock()
        self._limit_reason: str | None = None
        self._thread = Thread(
            target=self._capture,
            name=f"maverick-hosted-process-output-{process.pid}",
            daemon=True,
        )

    @property
    def limit_reason(self) -> str | None:
        with self._lock:
            return self._limit_reason

    def start(self) -> None:
        self._thread.start()

    def wait(self, timeout_seconds: float = 2.0) -> bool:
        return self._finished.wait(timeout_seconds)

    def _capture(self) -> None:
        stream = self.process.stdout
        if stream is None:
            self._set_reason("process_output_capture_failed")
            self.output_handle.close()
            self._finished.set()
            terminate_hosted_process(self.process)
            return
        selector = selectors.DefaultSelector()
        total = 0
        deadline = time.monotonic() + self.timeout_seconds
        try:
            selector.register(stream, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._set_reason("process_timed_out")
                    terminate_hosted_process(self.process)
                    break
                events = selector.select(timeout=min(remaining, 0.1))
                if not events:
                    continue
                chunk = os.read(stream.fileno(), 65_536)
                if not chunk:
                    break
                writable = min(len(chunk), MAX_PROCESS_OUTPUT_BYTES - total)
                if writable > 0:
                    self.output_handle.write(chunk[:writable])
                    total += writable
                if writable != len(chunk):
                    self._set_reason("process_output_too_large")
                    terminate_hosted_process(self.process)
                    break
        except Exception:
            self._set_reason("process_output_capture_failed")
            terminate_hosted_process(self.process)
        finally:
            selector.close()
            stream.close()
            self.output_handle.close()
            self._finished.set()

    def _set_reason(self, reason_code: str) -> None:
        with self._lock:
            if self._limit_reason is None:
                self._limit_reason = reason_code
