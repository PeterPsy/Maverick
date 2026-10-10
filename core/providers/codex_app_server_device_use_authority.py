"""Freeze native request authority before it waits in the provider queue."""

from contextlib import contextmanager
from dataclasses import dataclass

from core.device_use.models import DeviceUseSessionBinding


@dataclass(frozen=True)
class DeviceUseRequestAuthority:
    binding: DeviceUseSessionBinding | None
    provider_thread_id: str | None
    provider_turn_id: str | None
    runtime_turn_id: str | None
    task_text: str
    objective_revision: int
    correction_pending: bool

    def active(self, runtime) -> bool:
        with runtime.active_turn_lock:
            return (not self.correction_pending
                    and not runtime.device_use_correction_pending
                    and self.objective_revision == runtime.device_use_objective_revision
                    and self.binding == runtime.device_use_binding
                    and self.task_text == runtime.current_task_text
                    and self.provider_thread_id == runtime.provider_thread_id
                    and self.provider_turn_id == runtime.current_provider_turn_id
                    and self.runtime_turn_id == runtime.current_runtime_turn_id)


def capture_device_use_authority(runtime) -> DeviceUseRequestAuthority:
    with runtime.active_turn_lock:
        return DeviceUseRequestAuthority(
            runtime.device_use_binding, runtime.provider_thread_id,
            runtime.current_provider_turn_id, runtime.current_runtime_turn_id,
            runtime.current_task_text, runtime.device_use_objective_revision,
            runtime.device_use_correction_pending,
        )


@contextmanager
def device_use_correction(runtime):
    """Fence queued/active objectives before cancellation or provider I/O."""
    if runtime.device_use_binding is None:
        yield lambda: None
        return
    with runtime.active_turn_lock:
        runtime.device_use_objective_revision += 1
        revision = runtime.device_use_objective_revision
        runtime.device_use_correction_pending = True
    acknowledged = False

    def acknowledge():
        nonlocal acknowledged
        acknowledged = True

    try:
        yield acknowledge
    finally:
        if acknowledged:
            with runtime.active_turn_lock:
                if runtime.device_use_objective_revision == revision:
                    runtime.device_use_correction_pending = False
