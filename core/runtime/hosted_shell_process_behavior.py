"""Executable shell/process evidence for the hosted Full Workspace gate."""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.hosted_shell_process_behavior_support import (
    behavior_payload,
    build_behavior_runtime_store,
    invoke_behavior_capability,
    public_and_pairable,
    shell_process_result_policy,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities


HOSTED_SHELL_PROCESS_BEHAVIOR_IDS = (
    "core-capability:shell.run",
    "core-capability:process.start",
    "core-capability:process.status",
    "core-capability:process.input",
    "core-capability:process.interrupt",
)
_WORKSPACE_ID = "behavior-probe"
_SESSION_ID = "shell-process-behavior-probe"
_PROBE_TIME = datetime(2026, 9, 3, tzinfo=UTC)


@lru_cache(maxsize=1)
def inspect_hosted_shell_process_behavior() -> tuple[str, ...]:
    """Execute each real handler family once for this immutable code revision."""
    verified: set[str] = set()
    try:
        with tempfile.TemporaryDirectory() as directory:
            repository_root = Path(directory) / "maverick"
            workspace_root = repository_root / "workspaces" / _WORKSPACE_ID
            runtime_root = workspace_root / "runtime"
            for path in (
                repository_root / "core",
                repository_root / "apps",
                runtime_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
            (repository_root / "AGENTS.md").write_text("", encoding="utf-8")
            registry = HostedToolProcessRegistry(
                store=build_behavior_runtime_store(
                    workspace_root,
                    runtime_root,
                    workspace_id=_WORKSPACE_ID,
                    session_id=_SESSION_ID,
                    now=_PROBE_TIME,
                )
            )
            try:
                admission, preflight = shell_process_result_policy(
                    registry,
                    workspace_id=_WORKSPACE_ID,
                    now=_PROBE_TIME,
                )
                capabilities = {
                    surface.definition.handle: surface
                    for surface in build_core_runtime_tool_capabilities(
                        workspace_id=_WORKSPACE_ID,
                        workspace_root=workspace_root,
                        runtime_root=runtime_root,
                        process_registry=registry,
                        result_classification_resolver=admission,
                    )
                }
                context = RuntimeToolActorContext(
                    workspace_id=_WORKSPACE_ID,
                    actor_id="core-shell-process-probe",
                    agent_id="core-shell-process-probe",
                    platform_role="admin",
                    workspace_role="owner",
                    session_id=_SESSION_ID,
                    execution_mode="full-access",
                )
                _probe_shell(
                    capabilities,
                    context,
                    verified,
                    admission=admission,
                    preflight=preflight,
                )
                _probe_processes(
                    capabilities,
                    context,
                    verified,
                    admission=admission,
                    preflight=preflight,
                )
            finally:
                try:
                    registry.terminate_session(_SESSION_ID)
                except Exception:
                    verified.difference_update(
                        {
                            "core-capability:process.start",
                            "core-capability:process.status",
                            "core-capability:process.input",
                            "core-capability:process.interrupt",
                        }
                    )
    except Exception:
        return tuple(
            behavior
            for behavior in HOSTED_SHELL_PROCESS_BEHAVIOR_IDS
            if behavior in verified
        )
    return tuple(
        behavior
        for behavior in HOSTED_SHELL_PROCESS_BEHAVIOR_IDS
        if behavior in verified
    )


def _probe_shell(
    capabilities,
    context,
    verified: set[str],
    *,
    admission,
    preflight,
) -> None:
    try:
        arguments = {
            "argv": ["/bin/sh", "-c", "printf executable-shell"],
            "mutation_scopes": [],
        }
        result = invoke_behavior_capability(
            capabilities,
            "core-capability:shell.run",
            arguments,
            context,
            admission=admission,
            preflight=preflight,
        )
        payload = behavior_payload(result)
        if (
            public_and_pairable(result)
            and payload.get("exit_code") == 0
            and payload.get("output") == "executable-shell"
        ):
            verified.add("core-capability:shell.run")
    except Exception:
        return


def _probe_processes(
    capabilities,
    context,
    verified: set[str],
    *,
    admission,
    preflight,
) -> None:
    try:
        start_arguments = {
            "argv": [
                "/bin/sh",
                "-c",
                "read value; printf 'received:%s' \"$value\"",
            ],
            "mutation_scopes": [],
        }
        started = invoke_behavior_capability(
            capabilities,
            "core-capability:process.start",
            start_arguments,
            context,
            admission=admission,
            preflight=preflight,
        )
        started_payload = behavior_payload(started)
        process_id = str(started_payload.get("process_id") or "")
        if (
            public_and_pairable(started)
            and process_id
            and started_payload.get("status") == "running"
        ):
            verified.add("core-capability:process.start")
        input_arguments = {
            "process_id": process_id,
            "content": "hello\n",
            "close": True,
        }
        written = invoke_behavior_capability(
            capabilities,
            "core-capability:process.input",
            input_arguments,
            context,
            admission=admission,
            preflight=preflight,
        )
        if (
            public_and_pairable(written)
            and behavior_payload(written).get("accepted_bytes") == 6
        ):
            verified.add("core-capability:process.input")
        for _attempt in range(100):
            status = invoke_behavior_capability(
                capabilities,
                "core-capability:process.status",
                {"process_id": process_id},
                context,
                admission=admission,
                preflight=preflight,
            )
            status_payload = behavior_payload(status)
            if status_payload.get("status") != "running":
                if (
                    public_and_pairable(status)
                    and status_payload.get("status") == "exited"
                    and status_payload.get("exit_code") == 0
                    and status_payload.get("output") == "received:hello"
                ):
                    verified.add("core-capability:process.status")
                break
            time.sleep(0.01)

        interrupt_target = invoke_behavior_capability(
            capabilities,
            "core-capability:process.start",
            {
                "argv": ["/bin/sh", "-c", "while :; do sleep 1; done"],
                "mutation_scopes": [],
            },
            context,
            admission=admission,
            preflight=preflight,
        )
        interrupt_id = str(
            behavior_payload(interrupt_target).get("process_id") or ""
        )
        interrupted = invoke_behavior_capability(
            capabilities,
            "core-capability:process.interrupt",
            {"process_id": interrupt_id},
            context,
            admission=admission,
            preflight=preflight,
        )
        interrupted_payload = behavior_payload(interrupted)
        if (
            public_and_pairable(interrupted)
            and interrupted_payload.get("process_id") == interrupt_id
            and interrupted_payload.get("status") == "terminated"
            and interrupted_payload.get("terminated") is True
        ):
            verified.add("core-capability:process.interrupt")
    except Exception:
        return


__all__ = [
    "HOSTED_SHELL_PROCESS_BEHAVIOR_IDS",
    "inspect_hosted_shell_process_behavior",
]
