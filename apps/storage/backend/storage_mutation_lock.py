"""One bounded interprocess fence for Storage filesystem/index mutations."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
from threading import local
import time
from errors import StorageConflictError

_local = local()


@contextmanager
def storage_mutation_lock(data_root: Path, *, timeout: float = 1.0, shared: bool = False):
    path = data_root.absolute() / '.storage-write.lock'
    held = getattr(_local, 'held', None)
    if held is None:
        held = _local.held = {}
    if path in held:
        if held[path] and not shared:
            raise RuntimeError('Cannot upgrade an active Storage read fence.')
        yield
        return
    try:
        handle = path.open('a+')
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open('a+')
    with handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise StorageConflictError('Storage is busy; retry the operation.', conflict='storage_busy') from None
                time.sleep(0.01)
        held[path] = shared
        try:
            yield
        finally:
            del held[path]
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
