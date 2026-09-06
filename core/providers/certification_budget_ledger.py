"""Operator-owned, durable aggregate limits for disposable certification workers.

This is a spend/quota fence, not a credential grant or a release certificate.
Keep the ledger outside source/tenant mounts. Google free-tier status is an
operator assertion about the selected project, not something this ledger proves.
"""

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from core.providers.errors import CapabilityCertificateError


@dataclass(frozen=True)
class CertificationBudgetLimit:
    provider_id: str
    billing_mode: str
    max_cost_microusd: int
    max_requests: int
    min_interval_seconds: int

    def validate(self):
        expected = {"openrouter": "paid", "google-ai-studio": "free_tier"}
        if (expected.get(self.provider_id) != self.billing_mode
                or type(self.max_cost_microusd) is not int
                or type(self.max_requests) is not int or not 0 < self.max_requests <= 10_000
                or type(self.min_interval_seconds) is not int or not 0 <= self.min_interval_seconds <= 3600
                or (self.billing_mode == "paid" and not 0 < self.max_cost_microusd <= 5_000_000)
                or (self.billing_mode == "free_tier" and self.max_cost_microusd != 0)):
            raise CapabilityCertificateError("certification_budget_policy_invalid")


class CertificationBudgetLedger:
    """Reserve before transport; process exit/cancellation never refunds a call."""

    @classmethod
    def create(cls, path: Path, *, limits, authorization_ref: str):
        limits = tuple(limits)
        if not limits or len({item.provider_id for item in limits}) != len(limits) or not _digest(authorization_ref):
            raise CapabilityCertificateError("certification_budget_policy_invalid")
        for item in limits:
            item.validate()
        policy = json.dumps({
            "schema_version": 1, "authorization_ref": authorization_ref,
            "limits": [asdict(item) for item in sorted(limits, key=lambda item: item.provider_id)],
        }, sort_keys=True, separators=(",", ":"))
        _private_path(path, must_exist=False)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript("""
                PRAGMA synchronous=FULL;
                CREATE TABLE policy (document TEXT NOT NULL);
                CREATE TABLE reservations (
                    provider_id TEXT NOT NULL, cost INTEGER NOT NULL, created_at REAL NOT NULL,
                    payload_digest TEXT NOT NULL, run_id TEXT NOT NULL
                );
                CREATE TABLE halts (provider_id TEXT PRIMARY KEY, reason TEXT NOT NULL);
            """)
            connection.execute("INSERT INTO policy VALUES (?)", (policy,))
            connection.commit()
        return cls(path, policy_digest=hashlib.sha256(policy.encode()).hexdigest())

    def __init__(self, path: Path, *, policy_digest: str):
        self.path = Path(path)
        self.policy_digest = policy_digest
        if not _digest(policy_digest):
            raise CapabilityCertificateError("certification_budget_ledger_invalid")
        with self._connection():
            pass

    @contextmanager
    def _connection(self):
        connection = None
        try:
            _private_path(self.path)
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT document FROM policy").fetchall()
            if len(rows) != 1 or hashlib.sha256(rows[0][0].encode()).hexdigest() != self.policy_digest:
                raise ValueError
            policy = json.loads(rows[0][0])
            if policy["schema_version"] != 1 or not _digest(policy["authorization_ref"]):
                raise ValueError
            limits = [CertificationBudgetLimit(**value) for value in policy["limits"]]
            for item in limits:
                item.validate()
            if not limits or len({item.provider_id for item in limits}) != len(limits):
                raise ValueError
            yield connection, {item.provider_id: item for item in limits}
            connection.commit()
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise CapabilityCertificateError("certification_budget_ledger_invalid") from error
        finally:
            if connection is not None:
                connection.close()

    def reserve(self, *, provider_id: str, cost_microusd: int, payload_digest: str,
                run_id: str, now: float | None = None) -> float:
        """Return pacing delay without reserving, or zero after durable reservation."""
        instant = time.time() if now is None else now
        if (type(cost_microusd) is not int or not 0 < cost_microusd <= 100_000_000
                or not _digest(payload_digest) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", run_id)
                or type(instant) not in (float, int) or not math.isfinite(instant) or instant < 0):
            raise CapabilityCertificateError("certification_budget_request_invalid")
        with self._connection() as (connection, limits):
            limit = limits.get(provider_id)
            if limit is None:
                raise CapabilityCertificateError("certification_budget_provider_unapproved")
            if connection.execute("SELECT 1 FROM halts WHERE provider_id=?", (provider_id,)).fetchone():
                raise CapabilityCertificateError("certification_budget_halted")
            count, total, last = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(cost), 0), MAX(created_at) FROM reservations WHERE provider_id=?",
                (provider_id,),
            ).fetchone()
            if count >= limit.max_requests:
                raise CapabilityCertificateError("certification_budget_quota_exceeded")
            if limit.billing_mode == "paid" and total + cost_microusd > limit.max_cost_microusd:
                raise CapabilityCertificateError("certification_budget_exceeded")
            if last is not None and instant < last + limit.min_interval_seconds:
                return last + limit.min_interval_seconds - instant
            connection.execute("INSERT INTO reservations VALUES (?, ?, ?, ?, ?)", (
                provider_id, cost_microusd, instant, payload_digest, run_id,
            ))
        return 0.0

    def halt(self, provider_id: str, *, reason: str):
        """Stop a provider durably; resuming requires a separately authorized job."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", reason):
            raise CapabilityCertificateError("certification_budget_request_invalid")
        with self._connection() as (connection, limits):
            if provider_id not in limits:
                raise CapabilityCertificateError("certification_budget_provider_unapproved")
            connection.execute("INSERT OR IGNORE INTO halts VALUES (?, ?)", (provider_id, reason))

    def status(self):
        with self._connection() as (connection, limits):
            result = {}
            for provider, limit in limits.items():
                count, total = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(cost), 0) FROM reservations WHERE provider_id=?", (provider,),
                ).fetchone()
                halt = connection.execute("SELECT reason FROM halts WHERE provider_id=?", (provider,)).fetchone()
                result[provider] = {
                    **asdict(limit), "requests": count, "list_price_reserved_microusd": total,
                    "reserved_microusd": total if limit.billing_mode == "paid" else 0,
                    "halt_reason": halt[0] if halt else None,
                }
            return result


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _private_path(path: Path, *, must_exist=True):
    """An untrusted workspace must never own or mount this operator file."""
    if not path.is_absolute() or path.resolve() != path:
        raise CapabilityCertificateError("certification_budget_ledger_invalid")
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise CapabilityCertificateError("certification_budget_ledger_invalid")
    if not must_exist:
        return
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise CapabilityCertificateError("certification_budget_ledger_invalid")
