"""Heartbeat a delegation lease while supported OpenDesign calls are in flight."""

from __future__ import annotations

from threading import Event, Lock, Thread

from delegation_store import DelegationStore, DelegationStoreError, LEASE_SECONDS


class DelegationLeaseHeartbeat:
    """Keep one store owner live and surface any loss before the next side effect."""

    def __init__(
        self,
        store: DelegationStore,
        delegation_id: str,
        owner: str,
        *,
        interval_seconds: float | None = None,
    ) -> None:
        self.store = store
        self.delegation_id = delegation_id
        self.owner = owner
        self.interval_seconds = (
            max(0.01, float(interval_seconds))
            if interval_seconds is not None
            else max(1.0, LEASE_SECONDS / 3)
        )
        self._stop = Event()
        self._failure_lock = Lock()
        self._failure: Exception | None = None
        self._thread = Thread(
            target=self._run,
            name=f"delegation-lease-{delegation_id[-8:]}",
            daemon=True,
        )

    def __enter__(self) -> "DelegationLeaseHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_seconds * 2))

    def check(self) -> None:
        """Synchronously prove ownership immediately before a native side effect."""
        failure = self._stored_failure()
        if failure is not None:
            raise DelegationStoreError("Delegation operation lease was lost.") from failure
        try:
            self.store.heartbeat(self.delegation_id, self.owner)
        except Exception as error:
            self._remember_failure(error)
            raise DelegationStoreError("Delegation operation lease was lost.") from error

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.store.heartbeat(self.delegation_id, self.owner)
            except Exception as error:
                self._remember_failure(error)
                return

    def _remember_failure(self, error: Exception) -> None:
        with self._failure_lock:
            if self._failure is None:
                self._failure = error

    def _stored_failure(self) -> Exception | None:
        with self._failure_lock:
            return self._failure
