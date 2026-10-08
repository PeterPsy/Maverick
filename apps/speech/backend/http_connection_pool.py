"""Bounded keep-alive connections for Speech's remote audio providers."""

from __future__ import annotations

import http.client
from threading import Lock
from typing import Callable


ConnectionFactory = Callable[[str, float], http.client.HTTPSConnection]


class SpeechConnectionPool:
    def __init__(self, *, host: str, connection_factory: ConnectionFactory | None = None, max_idle: int = 4) -> None:
        self._connection_factory = connection_factory or _https_connection
        self._host = host
        self._max_idle = max(1, max_idle)
        self._idle: list[http.client.HTTPSConnection] = []
        self._lock = Lock()

    def acquire(self, *, timeout: float) -> tuple[http.client.HTTPSConnection, bool]:
        with self._lock:
            if self._idle:
                return self._idle.pop(), True
        return self._connection_factory(self._host, timeout), False

    def release(self, connection: http.client.HTTPSConnection) -> None:
        with self._lock:
            if len(self._idle) < self._max_idle:
                self._idle.append(connection)
                return
        connection.close()

    def discard(self, connection: http.client.HTTPSConnection) -> None:
        connection.close()

    def close(self) -> None:
        with self._lock:
            connections, self._idle = self._idle, []
        for connection in connections:
            connection.close()


def _https_connection(host: str, timeout: float) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, timeout=timeout)
