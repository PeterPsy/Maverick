from datetime import UTC, datetime, timedelta
import unittest

from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.transcript_projection import project_runtime_transcript
from core.runtime.turn_submission_service_output_text import _complete_output_text, _missing_final_suffix


class TranscriptMessageBoundariesTest(unittest.TestCase):
    def project(self, specs):
        events = [RuntimeEventRecord(
            event_id=str(index), workspace_id="default", session_id="session", turn_id="turn",
            plane="turn", process_id=None, event_type=kind, payload=payload,
            created_at=datetime(2026, 9, 30, tzinfo=UTC) + timedelta(seconds=index),
        ) for index, (kind, payload) in enumerate(specs)]
        return project_runtime_transcript(events, []).messages

    def test_repeated_completed_snapshot_does_not_make_an_aggregate_final(self):
        messages = self.project([
            ("runtime.output.delta", {"text": "Checking.\nWhich calendar?"}),
            ("runtime.output.delta", {"text": "Which calendar?", "provider_event_type": "item.completed"}),
            ("runtime.tool_call.completed", {"name": "test"}),
            ("runtime.output.delta", {"text": "Done.\n\n- Passed."}),
            ("runtime.output.final", {"text": "Checking.\nWhich calendar?Done.\n\n- Passed.", "complete_text": "Checking.\nWhich calendar?Done.\n\n- Passed."}),
        ])
        self.assertEqual([m.content for m in messages], ["Checking.\nWhich calendar?", "Done.\n\n- Passed."])

    def test_completed_messages_keep_their_boundaries(self):
        messages = self.project([
            ("runtime.output.delta", {"message_id": "progress", "text": "Checking."}),
            ("runtime.output.message.completed", {"message_id": "progress", "phase": "commentary"}),
            ("runtime.output.delta", {"message_id": "answer", "text": "Done.\n\n- Passed."}),
            ("runtime.output.message.completed", {"message_id": "answer", "phase": "final"}),
            ("runtime.output.final", {"text": "", "complete_text": "Done.\n\n- Passed."}),
        ])
        self.assertEqual([m.content for m in messages], ["Checking.", "Done.\n\n- Passed."])
        self.assertTrue(all(m.status == "complete" for m in messages))

    def test_streamed_final_answer_is_not_persisted_as_another_suffix(self):
        self.assertEqual(_missing_final_suffix("Done.", "Checking.Done."), "")
        self.assertEqual(_complete_output_text("Done.", "Checking.Done."), "Done.")
