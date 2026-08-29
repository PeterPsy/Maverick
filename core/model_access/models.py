"""Redaction-safe model-access bridge records."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal, Protocol

from core.model_access.cancellation import CancellationSignal


@dataclass(frozen=True)
class ModelAccessScope:
    """Authority carried by one private sidecar lease."""

    workspace_id: str
    app_id: str
    sidecar_id: str
    data_root: Path
    api: bool
    cli: tuple[str, ...]


@dataclass(frozen=True)
class ModelAccessModel:
    """One provider model exposed without any cognitive enrichment."""

    model_id: str
    label: str
    provider_id: str
    transport: Literal["api", "cli"]
    available: bool
    capabilities: dict[str, object] = field(default_factory=dict)

    def public_payload(self) -> dict[str, object]:
        return {
            "id": self.model_id,
            "label": self.label,
            "provider_id": self.provider_id,
            "transport": self.transport,
            "available": self.available,
            "capabilities": dict(self.capabilities),
        }


@dataclass(frozen=True)
class ModelAccessCatalog:
    """Models visible to one workspace/app capability."""

    api_models: tuple[ModelAccessModel, ...]
    cli_models: tuple[ModelAccessModel, ...]
    cli_defaults: dict[str, str] = field(default_factory=dict)

    def public_payload(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "api_models": [model.public_payload() for model in self.api_models],
            "cli_models": [model.public_payload() for model in self.cli_models],
            "cli_defaults": dict(self.cli_defaults),
        }


@dataclass(frozen=True)
class ModelAccessLease:
    """Private socket mount and bearer capability issued to one sidecar."""

    socket_directory: Path
    socket_path: Path
    sandbox_socket_path: str
    token: str
    release: Callable[[], None]


@dataclass(frozen=True)
class ProviderHttpResponse:
    """Streaming response returned by one exact provider transport."""

    status: int
    headers: tuple[tuple[str, str], ...]
    chunks: Iterable[bytes]
    close: Callable[[], None]


class ModelApiTransport(Protocol):
    """Open one content-preserving hosted-provider request."""

    def open(
        self,
        *,
        provider_id: str,
        body: bytes,
        credential: str,
        cancellation: CancellationSignal,
    ) -> ProviderHttpResponse: ...


@dataclass(frozen=True)
class CliFrame:
    """One stdout, stderr, or exit frame from a supervised CLI."""

    channel: Literal["stdout", "stderr", "exit"]
    payload: bytes


class ModelCliExecutor(Protocol):
    """Execute one approved local CLI invocation outside Maverick runtime."""

    def execute(
        self,
        *,
        scope: ModelAccessScope,
        provider_id: str,
        argv: tuple[str, ...],
        cwd: str,
        stdin: bytes,
        cancellation: CancellationSignal,
    ) -> Iterable[CliFrame]: ...
