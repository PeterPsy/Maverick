"""Provider-neutral asynchronous agentic runtime adapter contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.execution_binding import RuntimeExecutionBinding
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionRecord

if TYPE_CHECKING:
    from core.runtime.authority import EffectiveRuntimeAuthority


RuntimeProviderEventType = Literal[
    "provider.accepted",
    "provider.state.update",
    "provider.usage",
    "provider.lifecycle",
    "provider.request.sent",
    "provider.execution.completed",
    "runtime.output.delta",
    "runtime.output.final",
    "runtime.tool_call.proposed",
    "runtime.tool_call.awaiting_confirmation",
    "runtime.tool_call.authorized",
    "runtime.tool_call.started",
    "runtime.tool_call.completed",
    "runtime.tool_call.failed",
    "runtime.tool_call.execution_unknown",
    "runtime.warning",
    "runtime.error",
]


@dataclass(frozen=True)
class RuntimeProviderEvent:
    """One ordered provider-neutral event from an agentic adapter."""

    event_type: str
    correlation_id: str
    ordinal: int
    schema_version: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeHealth:
    status: Literal["healthy", "degraded", "unavailable"]
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeValidationContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding


@dataclass(frozen=True)
class RuntimePrepareContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    provider_state: RuntimeProviderState
    local_launch_spec: RuntimeBackendLaunchSpec | None = None


@dataclass(frozen=True)
class RuntimePrepareResult:
    ready: bool
    provider_state_updates: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    prepared_handle: object | None = None


@dataclass(frozen=True)
class RuntimeTurnContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    provider_state: RuntimeProviderState
    input_text: str
    correlation_id: str
    invoked_skills: tuple[object, ...] = ()
    timeout_seconds: int | None = None
    prepared_handle: object | None = None
    effective_authority: "EffectiveRuntimeAuthority | None" = None
    input_sources: tuple[object, ...] = ()


@dataclass(frozen=True)
class RuntimeCancelContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    provider_state: RuntimeProviderState
    correlation_id: str


@dataclass(frozen=True)
class RuntimeCancelResult:
    cancelled: bool
    reason_code: str


@dataclass(frozen=True)
class RuntimeRecoveryContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    provider_state: RuntimeProviderState
    trigger: str = "explicit_recovery"


@dataclass(frozen=True)
class RuntimeRecoveryResult:
    recovered: bool
    reason_code: str
    provider_state_updates: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeCloseContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    provider_state: RuntimeProviderState


@dataclass(frozen=True)
class RuntimeCloseResult:
    closed: bool
    terminated_processes: int = 0


@dataclass(frozen=True)
class RuntimeHealthContext:
    binding: RuntimeExecutionBinding


class AgenticRuntimeEngineAdapter(Protocol):
    """Async engine contract independent of processes and launch commands."""

    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    local_process_lifecycle: "LocalProcessRuntimeLifecycle | None"

    async def validate(self, context: RuntimeValidationContext) -> RuntimeHealth: ...

    async def prepare(self, context: RuntimePrepareContext) -> RuntimePrepareResult: ...

    def execute(self, context: RuntimeTurnContext) -> AsyncIterator[RuntimeProviderEvent]: ...

    async def cancel(self, context: RuntimeCancelContext) -> RuntimeCancelResult: ...

    async def recover(self, context: RuntimeRecoveryContext) -> RuntimeRecoveryResult: ...

    async def close(self, context: RuntimeCloseContext) -> RuntimeCloseResult: ...

    async def health(self, context: RuntimeHealthContext) -> RuntimeHealth: ...


@dataclass(frozen=True)
class LocalLaunchContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    secret_env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalProcessHandle:
    process_id: str
    pid: int | None
    opaque_handle: object | None = None


@dataclass(frozen=True)
class LocalPrewarmContext:
    session: RuntimeSessionRecord
    binding: RuntimeExecutionBinding
    launch_spec: RuntimeBackendLaunchSpec


@dataclass(frozen=True)
class LocalPrewarmResult:
    ready: bool
    provider_state_updates: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class LocalProcessRuntimeLifecycle(Protocol):
    """Optional lifecycle implemented only by local process engines."""

    async def build_launch_spec(self, context: LocalLaunchContext) -> RuntimeBackendLaunchSpec: ...

    async def start_process(self, spec: RuntimeBackendLaunchSpec) -> LocalProcessHandle: ...

    async def interrupt_process(self, handle: LocalProcessHandle) -> None: ...

    async def close_process(self, handle: LocalProcessHandle) -> None: ...

    async def prewarm(self, context: LocalPrewarmContext) -> LocalPrewarmResult: ...
