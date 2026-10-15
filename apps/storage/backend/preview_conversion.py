"""Bound concurrent Storage preview conversions across backend processes."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
from time import monotonic, sleep

from errors import StorageValidationError


@contextmanager
def conversion_slot(cache_root: Path, *, timeout: float = 60, slots: int = 1):
    cache_root.mkdir(parents=True, exist_ok=True)
    deadline = monotonic() + timeout
    while True:
        for index in range(slots):
            handle = (cache_root / f'.converter-{index}.lock').open('a+')
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
            return
        if monotonic() >= deadline:
            raise StorageValidationError('Preview conversion is busy; retry shortly.')
        sleep(.05)


@contextmanager
def cache_lock(cache_path: Path):
    with conversion_slot(cache_path.parent / '.locks' / cache_path.stem):
        yield
