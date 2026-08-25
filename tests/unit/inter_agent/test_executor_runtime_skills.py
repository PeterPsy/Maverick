from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.models import AgentParticipantSnapshot, ParticipantSpec
from core.inter_agent.service import InterAgentService
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    run_spec,
    runtime_state_namespace,
)


class InterAgentExecutorRuntimeSkillsTest(unittest.TestCase):
    def test_static_invocation_receipt_is_bounded_and_within_the_assigned_allowlist(self) -> None:
        for invoked_skill_ids, detail in (
            (["outside-allowlist"], "outside its assigned allowlist"),
            ([f"skill-{index}" for index in range(33)], "at most 32 skills"),
        ):
            with self.subTest(detail=detail):
                _repo_root, store, _runtime_store = build_executor_stores(self)
                participant = replace(
                    _explicit_runtime_participant(),
                    invoked_skill_ids=invoked_skill_ids,
                )
                with self.assertRaisesRegex(InterAgentValidationError, detail):
                    InterAgentService(store).create_run(
                        run_spec(
                            run_id=f"invalid-static-skills-{len(invoked_skill_ids)}",
                            participants=[participant],
                        ),
                        now=NOW,
                    )

    def test_static_modes_forward_the_participant_task_invocation_set(self) -> None:
        for mode in ("manager_tools", "sequential", "concurrent", "group_chat"):
            with self.subTest(mode=mode):
                _repo_root, store, runtime_store = build_executor_stores(self)
                service = InterAgentService(store)
                aggregator_participant_id = None
                if mode == "concurrent":
                    aggregator_participant_id = "orchestrator"
                elif mode == "group_chat":
                    aggregator_participant_id = "researcher"
                run = service.create_run(
                    run_spec(
                        mode=mode,
                        run_id=f"static-skills-{mode}",
                        participants=[_explicit_runtime_participant()],
                        aggregator_participant_id=aggregator_participant_id,
                        merge_policy="orchestrator_summarizes" if mode == "concurrent" else None,
                    ),
                    now=NOW,
                )
                submitted_skill_ids: list[list[str]] = []

                def fake_submit(
                    state,
                    *,
                    session,
                    input_text,
                    client_message_id=None,
                    invoked_skill_ids=None,
                    async_requested=False,
                ):
                    submitted_skill_ids.append(list(invoked_skill_ids or []))
                    turn = RuntimeTurnRecord(
                        turn_id=f"turn-{session.session_id}",
                        session_id=session.session_id,
                        workspace_id="default",
                        status="completed",
                        input_text=input_text,
                        created_at=NOW,
                        updated_at=NOW,
                        started_at=NOW,
                        completed_at=NOW,
                        failure_reason=None,
                        client_message_id=client_message_id,
                        invoked_skill_ids=list(invoked_skill_ids or []),
                    )
                    events = [
                        RuntimeEventRecord(
                            event_id=f"event-final-{session.session_id}",
                            workspace_id="default",
                            session_id=session.session_id,
                            plane="turn",
                            event_type="runtime.output.final",
                            turn_id=turn.turn_id,
                            process_id=None,
                            payload={"text": "Task complete."},
                            created_at=NOW,
                        )
                    ]
                    state.runtime_store.save_turn(turn)
                    for event in events:
                        state.runtime_store.save_event(event)
                    return turn, events

                with patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit):
                    execute_inter_agent_run(
                        service,
                        runtime_state_namespace(runtime_store),
                        workspace_id="default",
                        run_id=run.run_id,
                        input_text="$storage-ops use the selected storage capability.",
                        now=NOW,
                    )

                participant = store.get_participant(
                    "researcher",
                    workspace_id="default",
                    run_id=run.run_id,
                )
                task_event = next(
                    event
                    for event in store.list_event_page(
                        run.run_id,
                        workspace_id="default",
                        visibility_plane="debug",
                        limit=100,
                    ).events
                    if event.event_type == "inter_agent.task.created"
                )
                self.assertEqual(participant.invoked_skill_ids, ["storage-ops"])
                self.assertEqual(task_event.payload["invoked_skill_ids"], ["storage-ops"])
                self.assertEqual(submitted_skill_ids, [["storage-ops"]])


def _explicit_runtime_participant() -> ParticipantSpec:
    return ParticipantSpec(
        participant_id="researcher",
        kind="agent",
        execution_mode="child_runtime_session",
        label="Researcher",
        agent_type_id="storage-agent",
        agent_snapshot=AgentParticipantSnapshot(
            agent_type_id="storage-agent",
            label="Researcher",
            system_prompt="Use storage only when explicitly invoked.",
            skill_ids=["storage-ops"],
            skill_catalog_app_id="skills",
            skill_activation_mode="explicit",
        ),
        invoked_skill_ids=["storage-ops"],
    )


if __name__ == "__main__":
    unittest.main()
