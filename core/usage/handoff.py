"""Usage migration fence shared by document writers, SQLite, and operator cutover."""

from contextlib import contextmanager, nullcontext
from functools import wraps
import fcntl
import json
import os
from pathlib import Path
from threading import local
from time import monotonic, sleep
from uuid import uuid4

_HELD = local()
USAGE_ROOT = Path('data/control-plane/usage')


def selected_adapter() -> str:
    value = os.environ.get('MAVERICK_USAGE_STORE', 'document').strip().lower()
    if value not in {'document', 'sqlite'}:
        raise ValueError('MAVERICK_USAGE_STORE must be document or sqlite.')
    return value


def active_adapter(root: Path) -> str:
    try:
        value = json.loads((root / 'store.json').read_text())
    except FileNotFoundError:
        return 'document'
    if value.get('schema') != 1 or value.get('adapter') not in {'document', 'sqlite'}:
        raise RuntimeError('Unsupported Usage handoff marker.')
    return value['adapter']


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o660)
            json.dump(value, stream, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def usage_fence(root: Path, *, expected: str | None = None, exclusive: bool = False):
    key = str(root.absolute())
    held = getattr(_HELD, 'locks', None)
    if held is None:
        held = _HELD.locks = {}
    if key in held:
        if exclusive and not held[key]:
            raise RuntimeError('Cannot upgrade a Usage read fence.')
        yield
        return
    try:
        descriptor = os.open(root / '.migration.lock', os.O_RDONLY)
    except FileNotFoundError:
        try:
            root.mkdir(parents=True)
            root.chmod(0o2770)
        except FileExistsError:
            pass
        descriptor = os.open(root / '.migration.lock', os.O_RDONLY | os.O_CREAT, 0o660)
    with os.fdopen(descriptor, 'rb') as stream:
        deadline = monotonic() + 1.0
        while True:
            try:
                fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if monotonic() >= deadline:
                    raise RuntimeError('Usage migration is busy; retry after drain.') from None
                sleep(.01)
        try:
            if expected is not None and active_adapter(root) != expected:
                raise RuntimeError('Usage adapter changed; restart with the selected MAVERICK_USAGE_STORE.')
            held[key] = exclusive
            yield
        finally:
            held.pop(key, None)
            fcntl.flock(stream, fcntl.LOCK_UN)


def document_operation(method):
    """Fence nested document operations once; test-only in-memory stores need no disk fence."""
    @wraps(method)
    def operation(self, *args, **kwargs):
        with usage_fence(self.handoff_root, expected='document') if self.handoff_root else nullcontext():
            return method(self, *args, **kwargs)
    return operation
