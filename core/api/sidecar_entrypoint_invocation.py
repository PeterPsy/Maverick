"""Entrypoint runners that attach and revoke app-sidecar broker capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.api.sidecar_entrypoint_broker import (
    AppSidecarEntrypointBroker,
    SidecarEntrypointServiceTarget,
)
from core.api.sidecar_proxy import AuthorizedSidecarTarget
from core.apps.models import (
    HttpSidecarEntrypointSurface,
    ParsedAppContract,
    WorkspaceAppBindingRecord,
)
from core.shared.entrypoints import (
    EntrypointShutdownController,
    StreamingJsonEntrypointResult,
    run_json_entrypoint,
    run_streaming_json_entrypoint,
)


def sidecar_entrypoint_service_targets(
    *,
    binding: WorkspaceAppBindingRecord,
    source_root: Path,
    parsed: ParsedAppContract,
) -> list[SidecarEntrypointServiceTarget]:
    """Build trusted targets for sidecars declared by one resolved app binding."""
    return [
        SidecarEntrypointServiceTarget(
            target=AuthorizedSidecarTarget(
                binding=binding,
                source_root=source_root,
                parsed=parsed,
                sidecar=sidecar,
            )
        )
        for sidecar in parsed.contract.services.http_sidecars
        if sidecar.entrypoint_access is not None and sidecar.proxy is not None
    ]


def run_json_entrypoint_with_sidecars(
    entrypoint_path: str | Path,
    *,
    payload: dict[str, Any],
    cwd: str | Path,
    binding: WorkspaceAppBindingRecord,
    parsed: ParsedAppContract,
    surface: HttpSidecarEntrypointSurface,
    start_path: Path,
    actor_user_id: str | None,
    runtime_session_id: str | None,
    observability_store=None,
    timeout_seconds: int | float = 30,
    shutdown_controller: EntrypointShutdownController | None = None,
    entrypoint_runner: Callable[..., dict[str, Any]] = run_json_entrypoint,
) -> dict[str, Any]:
    """Run one JSON entrypoint with same-invocation capabilities when declared."""
    broker = _broker_for_invocation(
        binding=binding,
        source_root=Path(cwd),
        parsed=parsed,
        surface=surface,
        start_path=start_path,
        actor_user_id=actor_user_id,
        runtime_session_id=runtime_session_id,
        observability_store=observability_store,
        shutdown_controller=shutdown_controller,
    )
    descriptor = broker.start()
    try:
        entrypoint_payload = dict(payload)
        if descriptor is not None:
            entrypoint_payload["app_sidecar"] = descriptor
            entrypoint_payload["entrypoint_invocation_id"] = broker.invocation_id
        return entrypoint_runner(
            entrypoint_path,
            payload=entrypoint_payload,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            shutdown_controller=shutdown_controller,
        )
    finally:
        broker.close()


def run_streaming_json_entrypoint_with_sidecars(
    entrypoint_path: str | Path,
    *,
    payload: dict[str, Any],
    cwd: str | Path,
    binding: WorkspaceAppBindingRecord,
    parsed: ParsedAppContract,
    surface: HttpSidecarEntrypointSurface,
    start_path: Path,
    actor_user_id: str | None,
    runtime_session_id: str | None,
    observability_store=None,
    timeout_seconds: int | float = 30,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> StreamingJsonEntrypointResult:
    """Keep capabilities alive until a streaming entrypoint process closes."""
    broker = _broker_for_invocation(
        binding=binding,
        source_root=Path(cwd),
        parsed=parsed,
        surface=surface,
        start_path=start_path,
        actor_user_id=actor_user_id,
        runtime_session_id=runtime_session_id,
        observability_store=observability_store,
        shutdown_controller=shutdown_controller,
    )
    descriptor = broker.start()
    try:
        entrypoint_payload = dict(payload)
        if descriptor is not None:
            entrypoint_payload["app_sidecar"] = descriptor
            entrypoint_payload["entrypoint_invocation_id"] = broker.invocation_id
        result = run_streaming_json_entrypoint(
            entrypoint_path,
            payload=entrypoint_payload,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            shutdown_controller=shutdown_controller,
        )
    except Exception:
        broker.close()
        raise
    if result.has_stream:
        result.add_cleanup(broker.close)
    else:
        broker.close()
    return result


def _broker_for_invocation(
    *,
    binding: WorkspaceAppBindingRecord,
    source_root: Path,
    parsed: ParsedAppContract,
    surface: HttpSidecarEntrypointSurface,
    start_path: Path,
    actor_user_id: str | None,
    runtime_session_id: str | None,
    observability_store,
    shutdown_controller: EntrypointShutdownController | None,
) -> AppSidecarEntrypointBroker:
    return AppSidecarEntrypointBroker(
        services=sidecar_entrypoint_service_targets(
            binding=binding,
            source_root=source_root,
            parsed=parsed,
        ),
        surface=surface,
        actor_user_id=actor_user_id,
        runtime_session_id=runtime_session_id,
        start_path=start_path,
        observability_store=observability_store,
        shutdown_controller=shutdown_controller,
    )
