"""Redaction-safe Antigravity subscription usage reader."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from core.providers.antigravity_cli_runtime_home import (
    prepare_antigravity_runtime_home,
)
from core.providers.errors import (
    AgenticRuntimeError,
    ProviderUsageUnavailableError,
)
from core.providers.models import (
    ProviderSubscriptionUsage,
    ProviderUsageLimit,
    ProviderUsageWindow,
)
from core.providers.native_runtime_artifact import (
    ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
    inspect_native_runtime_artifact,
)
from core.providers.native_structured_cli_transport import (
    NativeStructuredCliError,
)
from core.runtime.workspace_sandbox import build_bwrap_command


ANTIGRAVITY_USAGE_MAX_BYTES = 64 * 1024
ANTIGRAVITY_USAGE_MAX_GROUPS = 32
ANTIGRAVITY_USAGE_MAX_BUCKETS = 8
AntigravityUsageRunner = Callable[[str, Sequence[Path], str | Path | None], str]


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def read_antigravity_subscription_usage(
    command: str,
    *,
    dependency_roots: Sequence[Path] = (),
    auth_home: str | Path | None = None,
    runner: AntigravityUsageRunner | None = None,
    now: datetime | None = None,
) -> ProviderSubscriptionUsage:
    """Read model-group quotas through Antigravity's read-only usage command."""
    try:
        raw_payload = (runner or _run_usage_command)(
            command,
            dependency_roots,
            auth_home,
        )
        payload = json.loads(raw_payload)
    except ProviderUsageUnavailableError:
        raise
    except (TypeError, ValueError) as error:
        raise ProviderUsageUnavailableError("usage_not_reported") from error
    if not isinstance(payload, dict):
        raise ProviderUsageUnavailableError("usage_not_reported")
    return _usage_from_payload(payload, now=now or utcnow())


def _run_usage_command(
    command: str,
    dependency_roots: Sequence[Path],
    auth_home: str | Path | None,
) -> str:
    executable = shutil.which(str(command or "").strip())
    if executable is None:
        raise ProviderUsageUnavailableError("provider_unavailable")
    try:
        binary = Path(executable).resolve(strict=True)
        if inspect_native_runtime_artifact(str(binary)) != ANTIGRAVITY_CLI_RUNTIME_ARTIFACT:
            raise ProviderUsageUnavailableError("provider_unavailable")
        with tempfile.TemporaryDirectory(prefix="maverick-antigravity-usage-") as folder:
            runtime = Path(folder)
            home = prepare_antigravity_runtime_home(
                runtime,
                source_home=auth_home,
            )
            command_argv = build_bwrap_command(
                workspace_root=runtime,
                runtime_root=runtime,
                home_root=home,
                dependency_roots=[binary.parent, *dependency_roots],
                command=[
                    str(binary),
                    "--print",
                    "/usage",
                    "--output-format",
                    "json",
                ],
            )
            completed = subprocess.run(
                command_argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                cwd=runtime,
                env=_usage_environment(home, runtime),
            )
    except NativeStructuredCliError as error:
        reason = str(error)
        normalized = (
            "authentication_required"
            if "oauth_credential" in reason
            else "provider_unavailable"
        )
        raise ProviderUsageUnavailableError(normalized) from error
    except ProviderUsageUnavailableError:
        raise
    except (
        AgenticRuntimeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        UnicodeError,
    ) as error:
        raise ProviderUsageUnavailableError("provider_unavailable") from error
    if completed.returncode != 0:
        raise ProviderUsageUnavailableError("provider_unavailable")
    if (
        len(completed.stdout.encode("utf-8")) > ANTIGRAVITY_USAGE_MAX_BYTES
        or len(completed.stderr.encode("utf-8")) > ANTIGRAVITY_USAGE_MAX_BYTES
    ):
        raise ProviderUsageUnavailableError("provider_unavailable")
    return completed.stdout


def _usage_environment(home: Path, runtime: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "TMPDIR": str(runtime),
    }


def _usage_from_payload(
    payload: dict[str, object],
    *,
    now: datetime,
) -> ProviderSubscriptionUsage:
    if payload.get("status") != "SUCCESS":
        raise ProviderUsageUnavailableError("provider_unavailable")
    command = payload.get("command")
    if not isinstance(command, dict) or command.get("name") != "usage":
        raise ProviderUsageUnavailableError("usage_not_reported")
    data = command.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list) or len(groups) > ANTIGRAVITY_USAGE_MAX_GROUPS:
        raise ProviderUsageUnavailableError("usage_not_reported")

    limits: list[ProviderUsageLimit] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        label = _safe_label(group.get("name"), f"Model group {group_index + 1}")
        buckets = group.get("buckets")
        if not isinstance(buckets, list) or len(buckets) > ANTIGRAVITY_USAGE_MAX_BUCKETS:
            continue
        parsed_buckets = [
            parsed
            for bucket in buckets
            if isinstance(bucket, dict)
            for parsed in [_usage_bucket(bucket, now=now)]
            if parsed is not None
        ]
        for pair_index in range(0, len(parsed_buckets), 2):
            pair = parsed_buckets[pair_index : pair_index + 2]
            bucket_ids = ":".join(bucket_id for bucket_id, _window in pair)
            limits.append(
                ProviderUsageLimit(
                    limit_id=f"antigravity:{bucket_ids}",
                    label=label,
                    limit_reached=any(
                        window.used_percent >= 100
                        for _bucket_id, window in pair
                    ),
                    primary_window=pair[0][1],
                    secondary_window=pair[1][1] if len(pair) > 1 else None,
                )
            )
    if not limits:
        raise ProviderUsageUnavailableError("usage_not_reported")
    return ProviderSubscriptionUsage(
        provider_id="antigravity-cli",
        provider_label="Antigravity",
        available=True,
        fetched_at=now,
        limits=limits,
    )


def _usage_bucket(
    bucket: dict[str, object],
    *,
    now: datetime,
) -> tuple[str, ProviderUsageWindow] | None:
    remaining = _optional_float(bucket.get("remaining_fraction"))
    if remaining is None:
        return None
    remaining = max(0.0, min(1.0, remaining))
    reset_at = _parse_reset_time(bucket.get("reset_time"))
    reset_after = None
    if reset_at is not None:
        reset_after = max(0, int((reset_at - now).total_seconds()))
    bucket_id = _safe_identifier(bucket.get("id")) or _safe_identifier(
        bucket.get("name")
    )
    if not bucket_id:
        return None
    return (
        bucket_id,
        ProviderUsageWindow(
            used_percent=(1.0 - remaining) * 100.0,
            limit_window_seconds=_window_seconds(bucket.get("window")),
            reset_after_seconds=reset_after,
            reset_at_epoch_seconds=int(reset_at.timestamp()) if reset_at is not None else None,
        ),
    )


def _window_seconds(value: object) -> int | None:
    normalized = str(value or "").strip().lower()
    aliases = {
        "hourly": 3600,
        "daily": 86400,
        "weekly": 604800,
    }
    if normalized in aliases:
        return aliases[normalized]
    match = re.fullmatch(r"(\d+)(m|h|d|w)", normalized)
    if match is None:
        return None
    unit_seconds = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    return int(match.group(1)) * unit_seconds[match.group(2)]


def _parse_reset_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_identifier(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or any(ord(character) < 32 for character in text):
        return ""
    return re.sub(r"[^A-Za-z0-9._:-]+", "-", text).strip("-")


def _safe_label(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 256 or any(ord(character) < 32 for character in text):
        return fallback
    return text


def _optional_float(value: object) -> float | None:
    try:
        parsed = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and math.isfinite(parsed) else None


__all__ = [
    "ANTIGRAVITY_USAGE_MAX_BYTES",
    "AntigravityUsageRunner",
    "read_antigravity_subscription_usage",
]
