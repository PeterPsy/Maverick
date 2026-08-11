"""Process-local ordering boundary for runtime message admission."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock


@dataclass
class _MessageAdmissionEntry:
    lock: RLock
    users: int = 0


_MESSAGE_ADMISSION_LOCKS: dict[str, _MessageAdmissionEntry] = {}
_MESSAGE_ADMISSION_LOCKS_LOCK = RLock()


@contextmanager
def runtime_message_admission_handoff(session_id: str):
    """Serialize steer and queue decisions for one runtime session."""
    with _MESSAGE_ADMISSION_LOCKS_LOCK:
        entry = _MESSAGE_ADMISSION_LOCKS.get(session_id)
        if entry is None:
            entry = _MessageAdmissionEntry(lock=RLock())
            _MESSAGE_ADMISSION_LOCKS[session_id] = entry
        entry.users += 1
    try:
        with entry.lock:
            yield
    finally:
        with _MESSAGE_ADMISSION_LOCKS_LOCK:
            entry.users -= 1
            if entry.users == 0 and _MESSAGE_ADMISSION_LOCKS.get(session_id) is entry:
                _MESSAGE_ADMISSION_LOCKS.pop(session_id, None)
