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
                or (self.billing_mode == "paid" and not 0 < self.max_cost_microusd <= 100_000_000)
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
        return cls._create_file(path, policy)

    @classmethod
    def create_successor(
        cls,
        path: Path,
        *,
        predecessor: "CertificationBudgetLedger",
        limits,
        authorization_ref: str,
    ):
        """Start a newly authorized job without restoring spent quota or credit.

        The predecessor is sealed before its counters are copied.  A failed
        successor creation therefore leaves the old job stopped rather than
        opening a race in which both ledgers can authorize provider traffic.
        """
        path = Path(path)
        _private_path(path, must_exist=False)
        if path.exists():
            raise FileExistsError(path)
        limits = tuple(limits)
        if (
            not limits
            or len({item.provider_id for item in limits}) != len(limits)
            or not _digest(authorization_ref)
        ):
            raise CapabilityCertificateError("certification_budget_policy_invalid")
        for item in limits:
            item.validate()
        snapshot = predecessor._seal_for_successor(
            limits=limits,
            authorization_ref=authorization_ref,
        )
        policy = json.dumps(
            {
                "schema_version": 2,
                "authorization_ref": authorization_ref,
                "limits": [
                    asdict(item)
                    for item in sorted(limits, key=lambda item: item.provider_id)
                ],
                "predecessor_policy_digest": predecessor.policy_digest,
                "predecessor_status_digest": snapshot["status_digest"],
                "carried_usage": snapshot["carried_usage"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls._create_file(path, policy)

    @classmethod
    def _create_file(cls, path: Path, policy: str):
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

    def _seal_for_successor(self, *, limits, authorization_ref: str) -> dict[str, object]:
        with self._connection() as (connection, predecessor_limits, metadata):
            if authorization_ref == metadata["authorization_ref"]:
                raise CapabilityCertificateError("certification_budget_policy_invalid")
            existing_halts = {
                provider: reason
                for provider, reason in connection.execute(
                    "SELECT provider_id, reason FROM halts"
                ).fetchall()
            }
            if not existing_halts:
                raise CapabilityCertificateError(
                    "certification_budget_successor_predecessor_not_halted"
                )
            successor_limits = {item.provider_id: item for item in limits}
            if set(successor_limits) != set(predecessor_limits):
                raise CapabilityCertificateError("certification_budget_policy_invalid")
            for provider_id, previous in predecessor_limits.items():
                successor = successor_limits[provider_id]
                if (
                    successor.billing_mode != previous.billing_mode
                    or successor.max_cost_microusd > previous.max_cost_microusd
                    or successor.max_requests > previous.max_requests
                    or successor.min_interval_seconds < previous.min_interval_seconds
                ):
                    raise CapabilityCertificateError(
                        "certification_budget_policy_invalid"
                    )
            carried_usage = []
            for provider_id in sorted(predecessor_limits):
                local_count, local_total, local_last = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(cost), 0), MAX(created_at) "
                    "FROM reservations WHERE provider_id=?",
                    (provider_id,),
                ).fetchone()
                previous = metadata["carried_usage"].get(provider_id, {})
                previous_last = previous.get("last_reserved_at")
                candidates = [
                    value
                    for value in (previous_last, local_last)
                    if value is not None
                ]
                carried_usage.append(
                    {
                        "provider_id": provider_id,
                        "requests": previous.get("requests", 0) + local_count,
                        "list_price_reserved_microusd": (
                            previous.get("list_price_reserved_microusd", 0)
                            + local_total
                        ),
                        "last_reserved_at": max(candidates) if candidates else None,
                    }
                )
                connection.execute(
                    "INSERT OR IGNORE INTO halts VALUES (?, ?)",
                    (provider_id, "successor_created"),
                )
            sealed_halts = {
                provider: reason
                for provider, reason in connection.execute(
                    "SELECT provider_id, reason FROM halts ORDER BY provider_id"
                ).fetchall()
            }
            return {
                "carried_usage": carried_usage,
                "status_digest": hashlib.sha256(
                    json.dumps(
                        {
                            "policy_digest": self.policy_digest,
                            "carried_usage": carried_usage,
                            "halts": sealed_halts,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }

    def __init__(self, path: Path, *, policy_digest: str):
        self.path = Path(path)
        self.policy_digest = policy_digest
        if not _digest(policy_digest):
            raise CapabilityCertificateError("certification_budget_ledger_invalid")
        with self._connection():
            pass

    @property
    def authorization_ref(self) -> str:
        """Return the exact authorization bound into the immutable policy."""
        with self._connection() as (_connection, _limits, metadata):
            return metadata["authorization_ref"]

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
            if policy["schema_version"] not in {1, 2} or not _digest(policy["authorization_ref"]):
                raise ValueError
            limits = [CertificationBudgetLimit(**value) for value in policy["limits"]]
            for item in limits:
                item.validate()
            if not limits or len({item.provider_id for item in limits}) != len(limits):
                raise ValueError
            carried_usage: dict[str, dict[str, object]] = {}
            predecessor_policy_digest = None
            if policy["schema_version"] == 2:
                predecessor_policy_digest = policy["predecessor_policy_digest"]
                if (
                    not _digest(predecessor_policy_digest)
                    or not _digest(policy["predecessor_status_digest"])
                    or not isinstance(policy["carried_usage"], list)
                ):
                    raise ValueError
                for item in policy["carried_usage"]:
                    if not isinstance(item, dict) or set(item) != {
                        "provider_id",
                        "requests",
                        "list_price_reserved_microusd",
                        "last_reserved_at",
                    }:
                        raise ValueError
                    provider_id = item["provider_id"]
                    last = item["last_reserved_at"]
                    if (
                        provider_id in carried_usage
                        or provider_id not in {limit.provider_id for limit in limits}
                        or type(item["requests"]) is not int
                        or item["requests"] < 0
                        or type(item["list_price_reserved_microusd"]) is not int
                        or item["list_price_reserved_microusd"] < 0
                        or (
                            last is not None
                            and (
                                type(last) not in (int, float)
                                or not math.isfinite(last)
                                or last < 0
                            )
                        )
                    ):
                        raise ValueError
                    carried_usage[provider_id] = item
                if set(carried_usage) != {item.provider_id for item in limits}:
                    raise ValueError
            yield connection, {item.provider_id: item for item in limits}, {
                "authorization_ref": policy["authorization_ref"],
                "predecessor_policy_digest": predecessor_policy_digest,
                "carried_usage": carried_usage,
            }
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
        with self._connection() as (connection, limits, metadata):
            limit = limits.get(provider_id)
            if limit is None:
                raise CapabilityCertificateError("certification_budget_provider_unapproved")
            if connection.execute("SELECT 1 FROM halts WHERE provider_id=?", (provider_id,)).fetchone():
                raise CapabilityCertificateError("certification_budget_halted")
            count, total, last = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(cost), 0), MAX(created_at) FROM reservations WHERE provider_id=?",
                (provider_id,),
            ).fetchone()
            carried = metadata["carried_usage"].get(provider_id, {})
            count += carried.get("requests", 0)
            total += carried.get("list_price_reserved_microusd", 0)
            carried_last = carried.get("last_reserved_at")
            if carried_last is not None and (last is None or carried_last > last):
                last = carried_last
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
        with self._connection() as (connection, limits, _metadata):
            if provider_id not in limits:
                raise CapabilityCertificateError("certification_budget_provider_unapproved")
            connection.execute("INSERT OR IGNORE INTO halts VALUES (?, ?)", (provider_id, reason))

    def status(self):
        with self._connection() as (connection, limits, metadata):
            result = {}
            for provider, limit in limits.items():
                count, total = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(cost), 0) FROM reservations WHERE provider_id=?", (provider,),
                ).fetchone()
                carried = metadata["carried_usage"].get(provider, {})
                carried_count = carried.get("requests", 0)
                carried_total = carried.get("list_price_reserved_microusd", 0)
                count += carried_count
                total += carried_total
                halt = connection.execute("SELECT reason FROM halts WHERE provider_id=?", (provider,)).fetchone()
                result[provider] = {
                    **asdict(limit), "requests": count, "list_price_reserved_microusd": total,
                    "reserved_microusd": total if limit.billing_mode == "paid" else 0,
                    "halt_reason": halt[0] if halt else None,
                    "carried_requests": carried_count,
                    "carried_list_price_reserved_microusd": carried_total,
                    "predecessor_policy_digest": metadata["predecessor_policy_digest"],
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
