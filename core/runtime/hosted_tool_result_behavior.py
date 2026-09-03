"""Executable result-policy gate for the hosted Full Workspace contract."""

from __future__ import annotations

from core.runtime.hosted_filesystem_result_behavior import (
    FILESYSTEM_RESULT_BEHAVIOR_IDS,
    inspect_hosted_filesystem_result_behavior,
)
from core.runtime.hosted_result_security_behavior import (
    HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
    inspect_hosted_result_security_behavior,
)
from core.runtime.hosted_collaboration_behavior import (
    HOSTED_COLLABORATION_BEHAVIOR_IDS,
    inspect_hosted_collaboration_behavior,
)
from core.runtime.hosted_shell_process_behavior import (
    HOSTED_SHELL_PROCESS_BEHAVIOR_IDS,
    inspect_hosted_shell_process_behavior,
)


HOSTED_TOOL_RESULT_BEHAVIOR_REVISION = 10
HOSTED_REQUIRED_RESULT_BEHAVIOR_HANDLES = (
    *FILESYSTEM_RESULT_BEHAVIOR_IDS,
    *HOSTED_SHELL_PROCESS_BEHAVIOR_IDS,
    *HOSTED_COLLABORATION_BEHAVIOR_IDS,
    *HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
)


def inspect_hosted_tool_result_behavior() -> tuple[str, ...]:
    """Aggregate executable evidence from concrete capability families."""
    return (
        *inspect_hosted_filesystem_result_behavior(),
        *inspect_hosted_shell_process_behavior(),
        *inspect_hosted_collaboration_behavior(),
        *inspect_hosted_result_security_behavior(),
    )


__all__ = [
    "HOSTED_REQUIRED_RESULT_BEHAVIOR_HANDLES",
    "HOSTED_TOOL_RESULT_BEHAVIOR_REVISION",
    "inspect_hosted_tool_result_behavior",
]
