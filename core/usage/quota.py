"""Persist redaction-safe provider subscription quota observations."""

from __future__ import annotations

import hashlib
from typing import Iterable

from core.providers.models import ProviderSubscriptionUsage
from core.usage.models import ProviderQuotaSnapshotRecord
from core.usage.store import UsageDocumentStore


def record_provider_quota_snapshots(
    store: UsageDocumentStore,
    *,
    workspace_id: str,
    usages: Iterable[ProviderSubscriptionUsage],
) -> int:
    """Record each provider-reported window without credentials or account identifiers."""
    inserted = 0
    for usage in usages:
        if not usage.available:
            continue
        for limit in usage.limits:
            for window_kind, window in (
                ("primary", limit.primary_window),
                ("secondary", limit.secondary_window),
            ):
                if window is None:
                    continue
                identity = ":".join(
                    [
                        workspace_id,
                        usage.provider_id,
                        limit.limit_id,
                        window_kind,
                        usage.fetched_at.isoformat(),
                        str(window.used_percent),
                        str(window.reset_at_epoch_seconds),
                    ]
                )
                record = ProviderQuotaSnapshotRecord(
                    snapshot_id="provider-quota-" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    workspace_id=workspace_id,
                    provider_id=usage.provider_id,
                    plan_type=usage.plan_type,
                    limit_id=limit.limit_id,
                    limit_label=limit.label,
                    window_kind=window_kind,
                    used_percent=max(0.0, min(100.0, float(window.used_percent))),
                    limit_window_seconds=window.limit_window_seconds,
                    reset_at_epoch_seconds=window.reset_at_epoch_seconds,
                    limit_reached=limit.limit_reached,
                    observed_at=usage.fetched_at,
                )
                _persisted, was_inserted = store.save_quota_snapshot_if_absent(record)
                inserted += int(was_inserted)
    return inserted
