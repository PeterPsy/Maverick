"""Local host-infrastructure persistence, outside tenant workspaces."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from core.installation.errors import InstallationError
from core.installation.validation import record_id


class InstallationStore:
    def __init__(self, repository_root: Path):
        self.repository_root = repository_root.resolve()
        self.root = self.repository_root / ".maverick" / "installation"

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._safe(self.root / "control.lock")
        with (self.root / "control.lock").open("a") as lock:
            if os.geteuid() == 0:
                owner = self.root.stat()
                os.fchown(lock.fileno(), owner.st_uid, owner.st_gid)
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self, kind: str, key: str = "current") -> dict | None:
        path = self._path(kind, key)
        self._safe(path)
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return None

    def write(self, kind: str, value: dict, key: str = "current") -> dict:
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._safe(path)
        if os.geteuid() == 0:
            root_owner = self.root.stat()
            os.chown(path.parent, root_owner.st_uid, root_owner.st_gid)
        owner = path.stat() if path.exists() else self.root.stat()
        descriptor, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            if os.geteuid() == 0:
                os.chown(temporary, owner.st_uid, owner.st_gid)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return value

    def list_jobs(self) -> list[dict]:
        folder = self.root / "jobs"
        return sorted((self.read("jobs", path.stem) for path in folder.glob("*.json")),
                      key=lambda item: item["created_at"], reverse=True)

    @staticmethod
    def _safe(path):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise InstallationError("unsafe_installation_state")

    def _path(self, kind: str, key: str) -> Path:
        if kind not in {"configuration", "plans", "jobs", "worker"}:
            raise InstallationError("invalid_state_collection")
        if kind in {"plans", "jobs"}:
            record_id(key)
        elif key != "current":
            raise InstallationError("invalid_state_key")
        return self.root / kind / (key + ".json")
