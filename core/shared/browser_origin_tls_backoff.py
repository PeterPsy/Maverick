"""Bound retries after ACME failures across sessions and backend restarts."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re


DEFAULT_RETRY = timedelta(minutes=1)
MAX_RETRY = timedelta(days=7)
_RETRY_DATE = re.compile(r"retry after (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC", re.IGNORECASE)


def _path(private_root: Path, installation_domain: str, acme_ca: str) -> Path:
    scope = sha256(f"{installation_domain}\n{acme_ca}".encode()).hexdigest()[:24]
    return private_root / f"issuance-backoff-{scope}.json"


def issuance_retry_at(private_root: Path, installation_domain: str, acme_ca: str) -> datetime | None:
    """Read operator-visible retry metadata; it contains no credential material."""
    try:
        data = json.loads(_path(private_root, installation_domain, acme_ca).read_text())
        value = datetime.fromisoformat(data["retry_at"])
        return value if value.tzinfo is not None else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_issuance_failure(private_root: Path, installation_domain: str, acme_ca: str, error: Exception,
                            *, now: datetime | None = None) -> None:
    """Honor a CA retry date or briefly back off ordinary transport/client failures."""
    now = now or datetime.now(timezone.utc)
    retry_at = now + DEFAULT_RETRY
    stderr = getattr(error, "stderr", "") or ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    for match in _RETRY_DATE.finditer(str(stderr)):
        try:
            value = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        retry_at = max(retry_at, min(value, now + MAX_RETRY))
    path = _path(private_root, installation_domain, acme_ca)
    temporary = path.with_suffix(".tmp")
    # The caller holds the issuance lock; replace avoids a partial record after restart.
    try:
        temporary.write_text(json.dumps({"retry_at": retry_at.isoformat()}))
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError:
        # A full disk must retain the original fail-closed TLS error.
        return


def clear_issuance_backoff(private_root: Path, installation_domain: str, acme_ca: str) -> None:
    try:
        _path(private_root, installation_domain, acme_ca).unlink(missing_ok=True)
    except OSError:
        return
