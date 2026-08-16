"""Lifecycle handoff for the bounded provider-start handshake."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, ContextManager, Iterator

from core.runtime.errors import RuntimeProviderStateError, RuntimeTransitionError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore


class RuntimeProviderStartHandoff:
    """Hold one session lifecycle fence until the provider accepts a turn."""

    def __init__(self, store: RuntimeStore, *, session_id: str, turn_id: str | None = None) -> None:
        self.store = store
        self.session_id = session_id
        self.turn_id = turn_id
        self.session: RuntimeSessionRecord | None = None
        self._handoff: ContextManager[object] | None = None
        self._released = False

    def __enter__(self) -> "RuntimeProviderStartHandoff":
        location = self.store.get_session(self.session_id)
        self._handoff = self.store.session_lifecycle_handoff(
            workspace_id=location.workspace_id,
            session_id=location.session_id,
        )
        self._handoff.__enter__()
        try:
            session = self.store.get_session(self.session_id)
            if session.status not in {"created", "running"}:
                raise RuntimeTransitionError(
                    f"Cannot start a provider while session `{session.session_id}` is {session.status}."
                )
            if session.runtime_mode == "agentic":
                binding = session.execution_binding
                if binding is not None:
                    provider_state = self.store.get_provider_state(session.session_id)
                    if (
                        provider_state.runtime_engine_id != binding.runtime_engine_id
                        or provider_state.model_provider_id != binding.model_provider_id
                    ):
                        raise RuntimeProviderStateError(
                            f"Runtime provider state for session `{session.session_id}` does not match its binding."
                        )
            if self.turn_id is not None:
                turn = self.store.get_turn(self.turn_id)
                if turn.session_id != session.session_id or turn.status != "active":
                    raise RuntimeTransitionError(
                        f"Cannot start a provider while runtime turn `{self.turn_id}` is {turn.status}."
                    )
                if turn.cancellation_requested_at is not None:
                    raise RuntimeTransitionError(
                        f"Cannot start a provider while runtime turn `{self.turn_id}` has a pending cancellation."
                    )
            self.session = session
            return self
        except BaseException:
            self.release()
            raise

    def release_after(
        self,
        callback: Callable[[dict[str, object]], None] | None,
    ) -> Callable[[dict[str, object]], None]:
        """Return an acceptance callback that releases after observer persistence."""

        def accepted(metadata: dict[str, object]) -> None:
            try:
                if callback is not None:
                    callback(metadata)
            finally:
                self.release()

        return accepted

    def release(self) -> None:
        if self._released or self._handoff is None:
            return
        self._released = True
        self._handoff.__exit__(None, None, None)

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


@contextmanager
def runtime_provider_start_handoff(
    store: RuntimeStore,
    *,
    session_id: str,
    turn_id: str | None = None,
    on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
) -> Iterator[tuple[RuntimeSessionRecord, Callable[[dict[str, object]], None]]]:
    """Yield fresh provider input and the acceptance callback under one fence."""
    with RuntimeProviderStartHandoff(store, session_id=session_id, turn_id=turn_id) as handoff:
        assert handoff.session is not None
        yield handoff.session, handoff.release_after(on_provider_accepted)


def patch_runtime_session_metadata(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
    **updates: object,
) -> RuntimeSessionRecord:
    """Patch metadata using only identity from a potentially stale session value."""
    return store.patch_session_metadata(
        session_id=session.session_id,
        workspace_id=session.workspace_id,
        updates=updates,
    )


def provider_thread_recorder(
    state,
    *,
    session_id: str,
    provider_id: str,
) -> Callable[[str], None]:
    """Build the lifecycle-safe provider-thread metadata callback."""
    from core.runtime.provider_state_service import record_provider_thread_id

    return lambda provider_thread_id: record_provider_thread_id(
        state,
        session_id=session_id,
        provider_id=provider_id,
        provider_thread_id=provider_thread_id,
    )
