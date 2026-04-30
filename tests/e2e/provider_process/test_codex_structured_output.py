"""Split tests from tests.support.cases.runtime_execution_command_cases.RuntimeExecutionCommandTest."""

from __future__ import annotations

from tests.support.cases import runtime_execution_command_cases as cases


_SELECTED = {
    'test_codex_unknown_search_notification_is_emitted_as_generic_tool_event',
    'test_codex_app_cli_chat_render_output_is_emitted_as_structured_runtime_output',
    'test_codex_completed_agent_message_can_emit_structured_runtime_output',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.RuntimeExecutionCommandTest):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class CodexStructuredOutputTest(cases.RuntimeExecutionCommandTest):
    """Run the CodexStructuredOutputTest subset."""

    pass


_mask_unselected(CodexStructuredOutputTest)
