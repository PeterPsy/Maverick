"""Trusted native-runtime discovery, separate from fallback display metadata."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
from threading import RLock
from typing import TYPE_CHECKING

from core.providers.native_agent_catalog import (
    NativeAgentCatalogModel,
    NativeAgentCatalogSnapshot,
)
from core.providers.provider_codex_models import CODEX_MODEL_CATALOG_TTL_SECONDS
from core.runtime.execution_binding import canonical_digest

if TYPE_CHECKING:
    from core.providers.provider_codex import CodexProviderAdapter


_CACHE: dict[str, NativeAgentCatalogSnapshot] = {}
_LOCK = RLock()


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


__all__ = ["discover_codex_native_catalog"]
