"""Deterministic, monotonic workspace/user cohorts for PWA feature flags."""

from __future__ import annotations

import os
from collections.abc import Mapping
from hashlib import sha256


ROLLOUT_WORKSPACE_PERCENT_SUFFIX = "_ROLLOUT_WORKSPACE_PERCENT"
ROLLOUT_USER_PERCENT_SUFFIX = "_ROLLOUT_USER_PERCENT"
_FULL_PERCENT = 100
_BUCKETS_PER_PERCENT = 100


def pwa_rollout_allows(
    feature_name: str,
    *,
    environment: Mapping[str, str] | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    """Apply optional stable cohorts; malformed percentages fail closed."""
    source = os.environ if environment is None else environment
    return _dimension_allows(
        feature_name,
        "workspace",
        workspace_id,
        source.get(f"{feature_name}{ROLLOUT_WORKSPACE_PERCENT_SUFFIX}"),
    ) and _dimension_allows(
        feature_name,
        "user",
        user_id,
        source.get(f"{feature_name}{ROLLOUT_USER_PERCENT_SUFFIX}"),
    )


def _dimension_allows(feature_name: str, dimension: str, identifier: str | None, raw: object) -> bool:
    percentage = _percentage(raw)
    if percentage >= _FULL_PERCENT:
        return True
    if percentage <= 0:
        return False
    normalized_identifier = str(identifier or "").strip()
    if not normalized_identifier:
        return False
    digest = sha256(
        f"maverick-pwa-rollout-v1\0{feature_name}\0{dimension}\0{normalized_identifier}".encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % (_FULL_PERCENT * _BUCKETS_PER_PERCENT)
    return bucket < percentage * _BUCKETS_PER_PERCENT


def _percentage(raw: object) -> int:
    if raw is None:
        return _FULL_PERCENT
    value = str(raw).strip()
    if not value or not value.isascii() or not value.isdigit():
        return 0
    percentage = int(value)
    return percentage if 0 <= percentage <= _FULL_PERCENT else 0
