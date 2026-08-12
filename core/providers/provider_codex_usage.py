"""Redaction-safe Codex subscription usage reader."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.providers.errors import ProviderUsageUnavailableError
from core.providers.models import (
    ProviderSubscriptionUsage,
    ProviderUsageLimit,
    ProviderUsageWindow,
)


CODEX_USAGE_ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"
CodexUsageTransport = Callable[[str, dict[str, str], float], tuple[int, dict[str, object]]]


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def read_codex_subscription_usage(
    codex_home: Path,
    *,
    transport: CodexUsageTransport | None = None,
    now: datetime | None = None,
) -> ProviderSubscriptionUsage:
    """Read Codex account limits without exposing account or credential fields."""
    access_token, account_id = _read_codex_auth(Path(codex_home))
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Maverick/3 provider-usage",
    }
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    status, payload = (transport or _get_json)(CODEX_USAGE_ENDPOINT, headers, 8.0)
    if status in {401, 403}:
        raise ProviderUsageUnavailableError("authentication_required")
    if status < 200 or status >= 300:
        raise ProviderUsageUnavailableError("provider_unavailable")
    return _usage_from_payload(payload, now=now or utcnow())


def _read_codex_auth(codex_home: Path) -> tuple[str, str]:
    auth_path = codex_home / "auth.json"
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise ProviderUsageUnavailableError("authentication_required") from error
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(tokens, dict):
        raise ProviderUsageUnavailableError("authentication_required")
    access_token = str(tokens.get("access_token") or "").strip()
    account_id = str(tokens.get("account_id") or "").strip()
    if not access_token:
        raise ProviderUsageUnavailableError("authentication_required")
    return access_token, account_id


def _get_json(url: str, headers: dict[str, str], timeout_seconds: float) -> tuple[int, dict[str, object]]:
    request = urllib_request.Request(url, headers=headers, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8")
            payload = json.loads(body)
            return int(response.status), payload if isinstance(payload, dict) else {}
    except urllib_error.HTTPError as error:
        return int(error.code), {}
    except (OSError, TimeoutError, ValueError, TypeError) as error:
        raise ProviderUsageUnavailableError("provider_unavailable") from error


def _usage_from_payload(payload: dict[str, object], *, now: datetime) -> ProviderSubscriptionUsage:
    limits: list[ProviderUsageLimit] = []
    rate_limit = payload.get("rate_limit")
    if isinstance(rate_limit, dict):
        parsed = _usage_limit("codex", "Codex", rate_limit)
        if parsed is not None:
            limits.append(parsed)
    additional_limits = payload.get("additional_rate_limits")
    if isinstance(additional_limits, list):
        for index, item in enumerate(additional_limits):
            if not isinstance(item, dict) or not isinstance(item.get("rate_limit"), dict):
                continue
            label = str(item.get("limit_name") or item.get("metered_feature") or f"Additional limit {index + 1}")
            limit_id = str(item.get("metered_feature") or item.get("limit_name") or f"additional-{index + 1}")
            parsed = _usage_limit(
                limit_id,
                label,
                item["rate_limit"],
                metered_feature=str(item.get("metered_feature") or "").strip() or None,
            )
            if parsed is not None:
                limits.append(parsed)
    if not limits:
        raise ProviderUsageUnavailableError("usage_not_reported")
    credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else {}
    return ProviderSubscriptionUsage(
        provider_id="codex",
        provider_label="Codex",
        available=True,
        fetched_at=now,
        plan_type=str(payload.get("plan_type") or "").strip() or None,
        limits=limits,
        credits_balance=_optional_float(credits.get("balance")),
        credits_unlimited=bool(credits.get("unlimited")),
    )


def _usage_limit(
    limit_id: str,
    label: str,
    payload: dict[str, object],
    *,
    metered_feature: str | None = None,
) -> ProviderUsageLimit | None:
    primary = _usage_window(payload.get("primary_window"))
    secondary = _usage_window(payload.get("secondary_window"))
    if primary is None and secondary is None:
        return None
    return ProviderUsageLimit(
        limit_id=limit_id,
        label=label,
        metered_feature=metered_feature,
        limit_reached=bool(payload.get("limit_reached")),
        primary_window=primary,
        secondary_window=secondary,
    )


def _usage_window(value: object) -> ProviderUsageWindow | None:
    if not isinstance(value, dict):
        return None
    used_percent = _optional_float(value.get("used_percent"))
    if used_percent is None:
        return None
    return ProviderUsageWindow(
        used_percent=max(0.0, min(100.0, used_percent)),
        limit_window_seconds=_optional_int(value.get("limit_window_seconds")),
        reset_after_seconds=_optional_int(value.get("reset_after_seconds")),
        reset_at_epoch_seconds=_optional_int(value.get("reset_at")),
    )


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
