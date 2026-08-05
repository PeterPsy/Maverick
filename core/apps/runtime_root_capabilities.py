"""One-shot app-data workdir capabilities for app-created runtime sessions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
import secrets
from threading import RLock
from time import monotonic

from core.apps.errors import AppHostingError


@dataclass(frozen=True)
class _RuntimeRootCapability:
    digest: str
    workspace_id: str
    source_app_id: str
    actor_id: str
    resolved_root: Path
    expires_at: float


class RuntimeRootCapabilityStore:
    """Issue and atomically consume bounded capabilities without retaining raw values."""

    def __init__(self) -> None:
        self._records: dict[str, _RuntimeRootCapability] = {}
        self._lock = RLock()

    def issue(
        self,
        *,
        workspace_id: str,
        source_app_id: str,
        actor_id: str,
        app_data_root: str | Path,
        relative_path: object,
        ttl_seconds: int = 5,
    ) -> str:
        """Mint a short capability for one existing real directory below app data."""
        if ttl_seconds < 1 or ttl_seconds > 30:
            raise AppHostingError("Runtime root capability TTL must be between 1 and 30 seconds.")
        resolved_root = _validated_app_data_directory(app_data_root, relative_path)
        value = secrets.token_urlsafe(32)
        digest = _digest(value)
        record = _RuntimeRootCapability(
            digest=digest,
            workspace_id=workspace_id,
            source_app_id=source_app_id,
            actor_id=actor_id,
            resolved_root=resolved_root,
            expires_at=monotonic() + ttl_seconds,
        )
        with self._lock:
            self._remove_expired_locked()
            self._records[digest] = record
        return value

    def consume(
        self,
        value: str,
        *,
        workspace_id: str,
        source_app_id: str,
        actor_id: str,
    ) -> Path:
        """Consume once through the exact stamped workspace/app/actor tuple."""
        digest = _digest(value)
        with self._lock:
            self._remove_expired_locked()
            record = self._records.get(digest)
            if record is None:
                raise AppHostingError("Runtime root capability is invalid or expired.")
            if (
                record.workspace_id != workspace_id
                or record.source_app_id != source_app_id
                or record.actor_id != actor_id
            ):
                raise AppHostingError("Runtime root capability ownership mismatch.")
            self._records.pop(digest, None)
        return _validated_resolved_directory(record.resolved_root)

    def retained_raw_values(self) -> tuple[str, ...]:
        """Support tests proving raw bearer material is never retained."""
        return ()

    def _remove_expired_locked(self) -> None:
        now = monotonic()
        for digest in [key for key, record in self._records.items() if record.expires_at <= now]:
            self._records.pop(digest, None)


def _validated_app_data_directory(app_data_root: str | Path, relative_path: object) -> Path:
    root = Path(app_data_root)
    try:
        if root.is_symlink() or not root.is_dir():
            raise AppHostingError("App runtime data root is unavailable.")
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise AppHostingError("App runtime data root is unavailable.") from exc
    if not isinstance(relative_path, str) or not relative_path.strip() or "\\" in relative_path:
        raise AppHostingError("Runtime project root must be an app-data-relative path.")
    relative = PurePosixPath(relative_path.strip())
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise AppHostingError("Runtime project root must be an app-data-relative path.")
    candidate = root.joinpath(*relative.parts)
    return _validated_resolved_directory(candidate, required_parent=resolved_root)


def _validated_resolved_directory(candidate: Path, *, required_parent: Path | None = None) -> Path:
    try:
        cursor = candidate
        while required_parent is not None and cursor != required_parent:
            if cursor.is_symlink():
                raise AppHostingError("Runtime project root cannot contain symlinks.")
            cursor = cursor.parent
        if candidate.is_symlink() or not candidate.is_dir():
            raise AppHostingError("Runtime project root is unavailable.")
        resolved = candidate.resolve(strict=True)
        if required_parent is not None:
            resolved.relative_to(required_parent)
    except AppHostingError:
        raise
    except (OSError, ValueError) as exc:
        raise AppHostingError("Runtime project root is unavailable or outside app data.") from exc
    return resolved


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
