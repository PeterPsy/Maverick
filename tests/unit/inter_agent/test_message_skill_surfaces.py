from __future__ import annotations

from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.cli.inter_agent_commands import inter_agent_command_specs
from core.cli.models import CliInvocationContext
from core.inter_agent.models import BudgetPolicySpec, InterAgentRunSpec, ParticipantSpec
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.mcp.inter_agent_tools import inter_agent_tool_specs
from core.mcp.models import McpInvocationContext
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.support.repo import make_temp_repo_root


class InterAgentMessageSkillSurfacesTest(unittest.TestCase):
    def test_cli_and_mcp_send_forward_invoked_skill_ids(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(_run_spec())
        participant = store.get_participant("worker", workspace_id="default", run_id=run.run_id)
        turn = RuntimeTurnRecord(
            turn_id="turn-surface-skills",
            session_id="child-session",
            workspace_id="default",
            status="completed",
            input_text="Use storage.",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
            started_at=datetime.now(tz=UTC),
            completed_at=datetime.now(tz=UTC),
            failure_reason=None,
            invoked_skill_ids=["storage-ops"],
        )
        cli_handler = _handler(
            inter_agent_command_specs(runtime_store=object(), inter_agent_store=store),
            "inter-agent.messages.send",
            "command_id",
        )
        mcp_handler = _handler(
            inter_agent_tool_specs(runtime_store=object(), inter_agent_store=store),
            "inter_agent_message_send",
            "tool_name",
        )

        with patch.object(
            InterAgentService,
            "send_runtime_message",
            return_value=(participant, turn, []),
        ) as send:
            cli_handler(
                {
                    "run_id": run.run_id,
                    "participant_id": "worker",
                    "input_text": "Use storage.",
                    "invoked_skill_ids": ["storage-ops"],
                },
                CliInvocationContext(
                    caller_kind="operator",
                    workspace_id="default",
                    agent_id=None,
                    effective_mode="full-access",
                    user_id="operator",
                ),
            )
            mcp_handler(
                {
                    "run_id": run.run_id,
                    "participant_id": "worker",
                    "input_text": "Use storage.",
                    "invoked_skill_ids": ["storage-ops"],
                },
                McpInvocationContext(
                    caller_kind="operator",
                    workspace_id="default",
                    agent_id=None,
                    effective_mode="full-access",
                    user_id="operator",
                ),
            )

        self.assertEqual(
            [call.kwargs["invoked_skill_ids"] for call in send.call_args_list],
            [["storage-ops"], ["storage-ops"]],
        )


def _handler(specs, identifier: str, field: str):
    return next(handler for definition, handler in specs if getattr(definition, field) == identifier)


def _run_spec() -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id="root-session",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="manager_tools",
        created_by_user_id="operator",
        participants=[
            ParticipantSpec(
                participant_id="orchestrator",
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label="Orchestrator",
            ),
            ParticipantSpec(
                participant_id="worker",
                kind="agent",
                execution_mode="child_runtime_session",
                label="Worker",
            ),
        ],
        budget=BudgetPolicySpec(max_participants=2, max_total_turns=2, max_turns_per_participant=2),
        run_id="surface-skill-run",
        idempotency_key="surface-skill-run",
    )


if __name__ == "__main__":
    unittest.main()
