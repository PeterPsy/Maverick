"""Public runtime status projections keep arbitrary Core reasons private."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.api.provider_api import runtime_session_payload
from core.api.runtime_api import _session_payload
from core.api.settings_api import _runtime_session_settings_payload
from core.runtime.runtime_session import RuntimeSessionRecord


NOW = datetime(2026, 8, 26, tzinfo=UTC)


class PublicRuntimeStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = RuntimeSessionRecord(
            session_id="session-quarantined",
            workspace_id="default",
            agent_id="chat",
            status="recovery_required",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-quarantined",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
            recovery_reason_code="private:/srv/runtime/token=do-not-project",
        )
        self.settings_state = SimpleNamespace(
            workspace_store=SimpleNamespace(
                get_workspace=lambda _workspace_id: SimpleNamespace(name="Default")
            )
        )

    def test_arbitrary_recovery_detail_is_replaced_in_every_public_payload(self) -> None:
        payloads = (
            runtime_session_payload(self.session),
            _session_payload(self.session),
            _runtime_session_settings_payload(self.settings_state, self.session),
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(
                    payload["recovery_reason_code"],
                    "runtime_state_ambiguous",
                )
                self.assertNotIn("do-not-project", str(payload))
        self.assertNotIn("declared_remote_data_class", payloads[1])

    def test_allowlisted_remote_ambiguity_cause_is_preserved(self) -> None:
        session = replace(
            self.session,
            recovery_reason_code="remote_agentic_state_ambiguous",
        )

        self.assertEqual(
            runtime_session_payload(session)["recovery_reason_code"],
            "remote_agentic_state_ambiguous",
        )


if __name__ == "__main__":
    unittest.main()
