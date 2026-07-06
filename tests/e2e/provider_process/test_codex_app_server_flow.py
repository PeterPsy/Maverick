"""Split tests from tests.support.cases.runtime_execution_command_cases.RuntimeExecutionCommandTest."""

from __future__ import annotations

from tests.support.cases import runtime_execution_command_cases as cases


_SELECTED = {
    'test_codex_execution_uses_persistent_app_server_thread',
    'test_codex_execution_removes_provider_generated_system_skills_before_thread_start',
    'test_codex_prewarm_starts_runtime_thread_before_turn',
    'test_codex_completed_agent_message_without_delta_is_emitted',
    'test_codex_execution_has_no_default_turn_timeout',
    'test_codex_retryable_app_server_error_does_not_end_turn',
    'test_codex_terminal_app_server_error_is_returned_to_runtime',
    'test_codex_process_exit_before_turn_completed_unblocks_execution',
    'test_codex_command_output_delta_notifications_are_filtered',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.RuntimeExecutionCommandTest):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class CodexAppServerFlowTest(cases.RuntimeExecutionCommandTest):
    """Run the CodexAppServerFlowTest subset."""

    pass


_mask_unselected(CodexAppServerFlowTest)
