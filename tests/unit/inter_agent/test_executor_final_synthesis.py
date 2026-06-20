from __future__ import annotations

import unittest

from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.models import EdgeSpec
from core.inter_agent.service import InterAgentService
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    participant_spec as _participant,
    run_spec as _run_spec,
    runtime_state_namespace as _state,
)


class InterAgentExecutorFinalSynthesisTest(unittest.TestCase):
    def _stores(self):
        return build_executor_stores(self)

    def test_sequential_run_projects_reviewer_output_as_orchestrator_final_answer(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="sequential",
                run_id="sequential-final-synthesis",
                participants=[
                    _participant("implementer", "Implementer"),
                    _participant("reviewer", "Reviewer"),
                ],
                edges=[
                    EdgeSpec(source_id="orchestrator", target_id="implementer", kind="delegated", label="Implementation"),
                    EdgeSpec(source_id="implementer", target_id="reviewer", kind="reviewed_by", label="Review"),
                    EdgeSpec(source_id="reviewer", target_id="orchestrator", kind="produced", label="Final answer"),
                ],
            ),
            now=NOW,
        )

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Answer in at most 10 lines.",
            participant_inputs={
                "implementer": "Produce the draft.",
                "reviewer": "Return the orchestrator-ready final answer.",
            },
            controlled_participants={
                "implementer": {
                    "output_text": "Draft answer that should remain inside the participant transcript.",
                    "summary": "Draft prepared.",
                },
                "reviewer": {
                    "output_text": "Final answer ready for the user.",
                    "summary": "Final answer approved.",
                },
            },
            allow_synthetic_participants=True,
            project_summaries=False,
            now=NOW,
        )
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        final_summary = [
            event
            for event in events
            if event.event_type == "inter_agent.summary.updated" and event.payload.get("final_answer")
        ][-1]
        run_completed = next(event for event in events if event.event_type == "inter_agent.run.completed")
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)

        self.assertEqual(result.final_answer, "Final answer ready for the user.")
        self.assertNotIn("Implementer:", result.final_answer)
        self.assertNotIn("Reviewer:", result.final_answer)
        self.assertNotIn("Draft answer", result.final_answer)
        self.assertEqual(final_summary.participant_id, "orchestrator")
        self.assertEqual(final_summary.payload["summary"], "Multi-agent run completed. Final answer ready for the user.")
        self.assertEqual(final_summary.payload["final_answer"], "Final answer ready for the user.")
        self.assertEqual(final_summary.payload["source_participant_ids"], ["reviewer"])
        self.assertNotIn("Implementer:", final_summary.payload["summary"])
        self.assertNotIn("Reviewer:", final_summary.payload["summary"])
        self.assertNotIn("Draft answer", final_summary.payload["summary"])
        self.assertEqual(run_completed.payload["summary"], "Multi-agent run completed. Final answer ready for the user.")
        self.assertEqual(run_completed.payload["final_answer"], "Final answer ready for the user.")
        self.assertEqual(orchestrator.status, "completed")

    def test_sequential_worker_prompt_is_delegated_instead_of_raw_orchestration_request(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="sequential",
                run_id="sequential-delegated-prompt",
                participants=[
                    _participant("implementer", "Implementer"),
                    _participant("reviewer", "Reviewer"),
                ],
            ),
            now=NOW,
        )
        original_prompt = "Use two workers: one implementer and one reviewer. Answer the customer in 10 lines."

        execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text=original_prompt,
            participant_inputs={
                "implementer": "Produce the customer-facing answer.",
                "reviewer": "Return the final answer.",
            },
            controlled_participants={
                "implementer": {"output_text": "Draft.", "summary": "Draft done."},
                "reviewer": {"output_text": "Final.", "summary": "Final done."},
            },
            allow_synthetic_participants=True,
            project_summaries=False,
            now=NOW,
        )
        message_events = [
            event
            for event in store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
            if event.event_type == "inter_agent.message.sent"
        ]
        implementer_prompt = message_events[0].payload["input_text"]

        self.assertNotEqual(implementer_prompt, original_prompt)
        self.assertIn("You are a delegated worker in a Maverick multi-agent run.", implementer_prompt)
        self.assertIn("Complete only the delegated task below.", implementer_prompt)
        self.assertIn("User request content:", implementer_prompt)
        self.assertIn("Answer the customer in 10 lines.", implementer_prompt)
        self.assertNotIn("Use two workers", implementer_prompt)
        self.assertNotIn("one reviewer", implementer_prompt)

    def test_sequential_worker_prompt_strips_italian_routing_request(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="sequential",
                run_id="sequential-italian-routing-prompt",
                participants=[
                    _participant("implementer", "Implementer"),
                    _participant("reviewer", "Reviewer"),
                ],
            ),
            now=NOW,
        )
        original_prompt = (
            "Usa la modalit\u00e0 multi-agent. "
            "Implementer: prepara la risposta. "
            "Reviewer: controlla la risposta. "
            "Rispondi al cliente in massimo 10 righe."
        )

        execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text=original_prompt,
            participant_inputs={
                "implementer": "Prepara la risposta per il cliente.",
                "reviewer": "Restituisci la risposta finale.",
            },
            controlled_participants={
                "implementer": {"output_text": "Bozza.", "summary": "Bozza pronta."},
                "reviewer": {"output_text": "Finale.", "summary": "Finale pronta."},
            },
            allow_synthetic_participants=True,
            project_summaries=False,
            now=NOW,
        )
        message_events = [
            event
            for event in store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
            if event.event_type == "inter_agent.message.sent"
        ]
        implementer_prompt = message_events[0].payload["input_text"]

        self.assertIn("User request content:", implementer_prompt)
        self.assertIn("Rispondi al cliente in massimo 10 righe.", implementer_prompt)
        self.assertNotIn("Usa la modalit\u00e0 multi-agent", implementer_prompt)
        self.assertNotIn("Implementer: prepara la risposta", implementer_prompt)
        self.assertNotIn("Reviewer: controlla la risposta", implementer_prompt)

    def test_sequential_worker_prompt_keeps_italian_modality_content_request(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        cases = [
            (
                "scura",
                "Usa la modalit\u00e0 scura per il PDF. Mantieni i campi principali.",
                ["Usa la modalit\u00e0 scura per il PDF.", "Mantieni i campi principali."],
            ),
            (
                "compatta",
                "Utilizza la modalit\u00e0 compatta per il riepilogo. Conserva le date.",
                ["Utilizza la modalit\u00e0 compatta per il riepilogo.", "Conserva le date."],
            ),
            (
                "offline",
                "Utilizza la modalit\u00e0 offline per consultare i dati. Riassumi i risultati.",
                ["Utilizza la modalit\u00e0 offline per consultare i dati.", "Riassumi i risultati."],
            ),
        ]
        for label, original_prompt, expected_fragments in cases:
            with self.subTest(label=label):
                run = service.create_run(
                    _run_spec(
                        mode="sequential",
                        run_id=f"sequential-italian-modality-content-{label}",
                        participants=[_participant("implementer", "Implementer")],
                    ),
                    now=NOW,
                )

                execute_inter_agent_run(
                    service,
                    _state(runtime_store),
                    workspace_id="default",
                    run_id=run.run_id,
                    input_text=original_prompt,
                    participant_inputs={"implementer": "Prepara il documento richiesto."},
                    controlled_participants={"implementer": {"output_text": "Documento pronto.", "summary": "Documento pronto."}},
                    allow_synthetic_participants=True,
                    project_summaries=False,
                    now=NOW,
                )
                message_event = next(
                    event
                    for event in store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
                    if event.event_type == "inter_agent.message.sent"
                )
                implementer_prompt = message_event.payload["input_text"]

                self.assertIn("User request content:", implementer_prompt)
                for expected in expected_fragments:
                    self.assertIn(expected, implementer_prompt)


if __name__ == "__main__":
    unittest.main()
