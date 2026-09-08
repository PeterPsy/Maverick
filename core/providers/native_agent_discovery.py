"""Trusted native-runtime discovery, separate from fallback display metadata."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import RLock
from typing import TYPE_CHECKING

from core.providers.antigravity_cli_runtime_home import (
    ANTIGRAVITY_OAUTH_TOKEN_FILENAME,
    prepare_antigravity_runtime_home,
    resolve_antigravity_source_home,
    validate_antigravity_oauth_source,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.native_agent_catalog import (
    NativeAgentCatalogModel,
    NativeAgentCatalogSnapshot,
)
from core.providers.native_runtime_artifact import (
    ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
    inspect_native_runtime_artifact,
)
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.providers.models import ProviderModelOption
from core.providers.provider_codex_models import CODEX_MODEL_CATALOG_TTL_SECONDS
from core.runtime.execution_binding import canonical_digest
from core.runtime.workspace_sandbox import build_bwrap_command

if TYPE_CHECKING:
    from core.providers.provider_codex import CodexProviderAdapter


_CACHE: dict[str, NativeAgentCatalogSnapshot] = {}
_LOCK = RLock()
_ANTIGRAVITY_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_ANTIGRAVITY_CATALOG_MAX_BYTES = 64 * 1024
_ANTIGRAVITY_CATALOG_MAX_MODELS = 256


def discover_codex_native_catalog(
    adapter: CodexProviderAdapter, *, force: bool = False,
) -> NativeAgentCatalogSnapshot | None:
    """Only a successful configured CLI response grants fresh model availability."""
    command = adapter._runtime_command(adapter.codex_command)
    try:
        binary = Path(command).resolve()
        stat = binary.stat()
        source_id = canonical_digest((
            "codex-debug-models-v1", str(binary), stat.st_dev, stat.st_ino,
            stat.st_size, stat.st_mtime_ns,
            str(adapter._source_codex_home()),
            os.environ.get("CODEX_HOME", ""),
        ))
    except OSError:
        return None
    with _LOCK:
        timestamp = datetime.now(tz=UTC)
        cached = _CACHE.get(source_id)
        if not force and cached is not None and timestamp < cached.expires_at:
            return cached
        try:
            result = subprocess.run(
                [command, "debug", "models"], check=True, capture_output=True,
                text=True, timeout=5,
                env={**os.environ, "CODEX_HOME": str(adapter._source_codex_home())},
            )
            payload = json.loads(result.stdout)
            raw_models = payload.get("models")
            if not isinstance(raw_models, list):
                raise ValueError("native_agent_catalog_invalid")
            models, options = [], []
            seen = set()
            for item in raw_models:
                if not isinstance(item, dict):
                    raise ValueError("native_agent_catalog_invalid")
                option = adapter._model_option_from_catalog_item(item)
                if option is None:
                    continue
                if option.model_id in seen:
                    raise ValueError("native_agent_catalog_duplicate")
                seen.add(option.model_id)
                revision = item.get("model_revision")
                revision_policy = item.get("model_revision_policy", item.get(
                    "revision_policy", "exact" if revision is not None else "provider_alias",
                ))
                if (
                    revision_policy not in {"exact", "provider_alias"}
                    or (revision is not None and (
                        not isinstance(revision, str) or not revision.strip() or revision != revision.strip()
                    ))
                    or (revision_policy == "exact" and revision is None)
                ):
                    raise ValueError("native_agent_catalog_revision_invalid")
                model = NativeAgentCatalogModel(
                    model_provider_id="codex", model_id=option.model_id,
                    model_revision=revision, revision_policy=revision_policy,
                    reasoning_efforts=tuple(value.effort for value in option.supported_reasoning_efforts),
                    default_reasoning_effort=option.default_reasoning_effort,
                )
                models.append(model)
                options.append(replace(option, metadata={
                    "model_revision": revision, "model_revision_policy": revision_policy,
                    "native_model_catalog_digest": model.digest,
                }))
            snapshot = NativeAgentCatalogSnapshot(
                runtime_engine_id="codex", model_provider_id="codex", catalog_provider_id="codex",
                source_id=source_id, observed_at=timestamp,
                expires_at=timestamp + timedelta(seconds=CODEX_MODEL_CATALOG_TTL_SECONDS),
                models=tuple(models), model_options=tuple(options),
            )
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError):
            _CACHE.pop(source_id, None)
            return None
        _CACHE[source_id] = snapshot
        # Keep the unchanged certified launch adapter's settings validator in
        # sync with this same successful runtime observation (never fallback).
        adapter._store_model_options_cache(command, list(snapshot.model_options))
        return snapshot


def discover_antigravity_native_catalog(
    adapter,
    *,
    force: bool = False,
) -> NativeAgentCatalogSnapshot | None:
    """Discover Antigravity models through an exact binary and private OAuth copy."""
    command = shutil.which(str(getattr(adapter, "command", "") or ""))
    if command is None:
        return None
    binary = Path(command).resolve(strict=False)
    source_home = resolve_antigravity_source_home(
        getattr(adapter, "auth_home", None)
    )
    try:
        artifact = inspect_native_runtime_artifact(str(binary))
        if artifact != ANTIGRAVITY_CLI_RUNTIME_ARTIFACT:
            return None
        validate_antigravity_oauth_source(source_home)
        binary_details = binary.stat()
        source_details = source_home.stat(follow_symlinks=False)
        token_details = (
            source_home / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        ).stat(follow_symlinks=False)
        source_id = canonical_digest(
            (
                "antigravity-models-tab-v1",
                str(binary),
                binary_details.st_dev,
                binary_details.st_ino,
                artifact,
                str(source_home.resolve(strict=True)),
                _stat_fence(source_details),
                _stat_fence(token_details),
            )
        )
    except (
        CapabilityCertificateError,
        NativeStructuredCliError,
        OSError,
        RuntimeError,
    ):
        return None

    with _LOCK:
        timestamp = datetime.now(tz=UTC)
        cached = _CACHE.get(source_id)
        if not force and cached is not None and timestamp < cached.expires_at:
            return cached
        try:
            with tempfile.TemporaryDirectory(
                prefix="maverick-antigravity-catalog-"
            ) as folder:
                runtime = Path(folder)
                home = prepare_antigravity_runtime_home(
                    runtime,
                    source_home=source_home,
                )
                command_argv = build_bwrap_command(
                    workspace_root=runtime,
                    runtime_root=runtime,
                    home_root=home,
                    dependency_roots=[
                        binary.parent,
                        *tuple(getattr(adapter, "dependency_roots", ())),
                    ],
                    command=[str(binary), "models"],
                )
                completed = subprocess.run(
                    command_argv,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    cwd=runtime,
                    env=_antigravity_catalog_environment(home, runtime),
                )
                if (
                    len(completed.stdout.encode("utf-8"))
                    > _ANTIGRAVITY_CATALOG_MAX_BYTES
                    or len(completed.stderr.encode("utf-8"))
                    > _ANTIGRAVITY_CATALOG_MAX_BYTES
                ):
                    raise ValueError("native_agent_catalog_too_large")
                models, options = _parse_antigravity_catalog(completed.stdout)
            snapshot = NativeAgentCatalogSnapshot(
                runtime_engine_id="antigravity-cli",
                model_provider_id="google",
                catalog_provider_id="antigravity-cli",
                source_id=source_id,
                observed_at=timestamp,
                expires_at=timestamp
                + timedelta(seconds=CODEX_MODEL_CATALOG_TTL_SECONDS),
                models=tuple(models),
                model_options=tuple(options),
            )
        except (
            NativeStructuredCliError,
            OSError,
            subprocess.SubprocessError,
            UnicodeError,
            ValueError,
            RuntimeError,
        ):
            _CACHE.pop(source_id, None)
            return None
        _CACHE[source_id] = snapshot
        return snapshot


def _parse_antigravity_catalog(
    payload: str,
) -> tuple[list[NativeAgentCatalogModel], list[ProviderModelOption]]:
    lines = payload.splitlines()
    if lines and lines[0] == "Fetching available models...":
        lines = lines[1:]
    if not lines or len(lines) > _ANTIGRAVITY_CATALOG_MAX_MODELS:
        raise ValueError("native_agent_catalog_invalid")
    models: list[NativeAgentCatalogModel] = []
    options: list[ProviderModelOption] = []
    seen: set[str] = set()
    for line in lines:
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError("native_agent_catalog_invalid")
        model_id, label = parts
        if (
            not _ANTIGRAVITY_MODEL_ID.fullmatch(model_id)
            or not label
            or label != label.strip()
            or len(label) > 256
            or any(ord(character) < 32 for character in label)
            or model_id in seen
        ):
            raise ValueError("native_agent_catalog_invalid")
        seen.add(model_id)
        model = NativeAgentCatalogModel(
            model_provider_id="google",
            model_id=model_id,
            model_revision=None,
            revision_policy="provider_alias",
        )
        models.append(model)
        options.append(
            ProviderModelOption(
                model_id=model_id,
                label=label,
                description=(
                    "Model advertised by the authenticated Antigravity CLI "
                    "connection. Availability does not grant release authority."
                ),
                default_reasoning_effort=None,
                metadata={
                    "model_revision": None,
                    "model_revision_policy": "provider_alias",
                    "native_model_catalog_digest": model.digest,
                },
            )
        )
    return models, options


def _antigravity_catalog_environment(home: Path, runtime: Path) -> dict[str, str]:
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


def _stat_fence(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_uid,
        details.st_gid,
        details.st_nlink,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


__all__ = [
    "discover_antigravity_native_catalog",
    "discover_codex_native_catalog",
]
