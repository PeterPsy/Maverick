from __future__ import annotations

import unittest
from unittest.mock import patch

from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.service import InterAgentService
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    runtime_state_namespace,
)
from tests.unit.inter_agent.test_service_runtime import _run_spec


class InterAgentRuntimeSkillTest(unittest.TestCase):
    def test_explicit_runtime_message_does_not_expand_the_participant_allowlist(self) -> None:
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        assigned_skill_ids = [f"assigned-skill-{index}" for index in range(33)]
        run = service.create_run(
            _run_spec(
                idempotency_key="explicit-message-with-large-allowlist",
                researcher_snapshot=AgentParticipantSnapshot(
                    agent_type_id="research-agent",
                    label="Researcher",
                    system_prompt="Invoke only task-required skills.",
                    skill_ids=assigned_skill_ids,
                    skill_catalog_app_id="skills",
                    skill_activation_mode="explicit",
                ),
            ),
            now=NOW,
        )
        participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            now=NOW,
        )
        turn = RuntimeTurnRecord(
            turn_id="turn-large-allowlist",
            session_id=child.session_id,
            workspace_id="default",
            status="completed",
            input_text="perform the task",
            created_at=NOW,
            updated_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            failure_reason=None,
        )

        with patch("core.inter_agent.service.submit_runtime_turn", return_value=(turn, [])) as submit:
            service.send_runtime_message(
                runtime_state_namespace(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                participant_id=participant.participant_id,
                input_text="perform the task",
                now=NOW,
            )

        self.assertEqual(submit.call_args.kwargs["invoked_skill_ids"], [])


if __name__ == "__main__":
    unittest.main()
