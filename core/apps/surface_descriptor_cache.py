"""Bounded parsing cache for immutable app discovery descriptors, never app data."""

from collections import OrderedDict
import json
from pathlib import Path
from threading import RLock

_lock = RLock()
_entries: OrderedDict[Path, tuple[tuple, dict, int]] = OrderedDict()
_bytes = 0
_MAX_BYTES = 8 * 1024 * 1024
_MAX_FILES = 128


def _signature(info) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_descriptor_object(path: Path) -> dict:
    """Return an internal read-only object; public callers copy just the selected item."""
    global _bytes
    key = path.absolute()
    signature = _signature(path.stat())
    with _lock:
        cached = _entries.get(key)
        if cached and cached[0] == signature:
            _entries.move_to_end(key)
            return cached[1]
    raw = path.read_bytes()
    if _signature(path.stat()) != signature:
        # A deployment changed the descriptor during the read. Never cache a mixed version.
        raise ValueError(f'App surface descriptor `{path}` changed during discovery; retry.')
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'App surface descriptor `{path}` is not valid JSON.') from error
    if not isinstance(payload, dict):
        raise ValueError(f'App surface descriptor `{path}` must be a JSON object.')
    with _lock:
        previous = _entries.pop(key, None)
        if previous:
            _bytes -= previous[2]
        if len(raw) <= _MAX_BYTES:
            _entries[key] = (signature, payload, len(raw))
            _bytes += len(raw)
            while _bytes > _MAX_BYTES or len(_entries) > _MAX_FILES:
                _, removed = _entries.popitem(last=False)
                _bytes -= removed[2]
    return payload
