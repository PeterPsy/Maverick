"""Containment-first recovery fault-injection regressions."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from core.providers.agentic_adapter import RuntimeRecoveryContext
from core.runtime.public_status import PUBLIC_RUNTIME_RECOVERY_REASON_CODES
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.runtime_state import test_hosted_agentic_recovery as recovery_tests


class HostedAgenticRecoveryContainmentTest(unittest.TestCase):
    _begin = recovery_tests.HostedAgenticRecoveryTest._begin

    def test_quarantine_survives_diagnostic_journal_cas_and_projection_faults(self) -> None:
        cases = (
            "store_recovery_detail",
            "journal_require_recovery",
            "journal_cas_conflict",
            "session_cas_conflict",
            "runtime_state_projection",
        )
        for case in cases:
            with self.subTest(case=case):
                harness = HostedAgenticHarness(self)
                adapter = harness.adapter(DeterministicFakeAgenticClient())
                record = self._begin(harness, adapter, f"request-{case}")
                record = adapter.loop.provider_step_journal.accept(
                    record,
                    provider_response_id=f"response-{case}",
                    provider_upstream_id=None,
                )
                adapter.loop.provider_step_journal.fail_stream(
                    record,
                    reason_code="provider_response_invalid",
                )
                if case == "store_recovery_detail":
                    target = patch.object(
                        harness.private_state_service,
                        "store_recovery_detail",
                        side_effect=RuntimeError("private diagnostic unavailable"),
                    )
                elif case == "journal_require_recovery":
                    target = patch.object(
                        adapter.loop.provider_step_journal,
                        "require_recovery",
                        side_effect=RuntimeError("journal unavailable"),
                    )
                elif case == "journal_cas_conflict":
                    original = harness.store.update_provider_step_journal
                    calls = 0

                    def conflict_once(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            from core.runtime.errors import RuntimeProviderStateError

                            raise RuntimeProviderStateError(
                                "provider_step_journal_revision_conflict"
                            )
                        return original(*args, **kwargs)

                    target = patch.object(
                        harness.store,
                        "update_provider_step_journal",
                        side_effect=conflict_once,
                    )
                elif case == "session_cas_conflict":
                    original = harness.store.save_session_if_status
                    calls = 0

                    def conflict_once(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            from core.runtime.errors import RuntimeTransitionError

                            raise RuntimeTransitionError(
                                "runtime_session_expected_status_changed"
                            )
                        return original(*args, **kwargs)

                    target = patch.object(
                        harness.store,
                        "save_session_if_status",
                        side_effect=conflict_once,
                    )
                else:
                    target = patch.object(
                        harness.store,
                        "save_state",
                        side_effect=RuntimeError("runtime projection unavailable"),
                    )
                with target:
                    result = asyncio.run(
                        adapter.recover(
                            RuntimeRecoveryContext(
                                harness.session,
                                harness.binding,
                                harness.store.get_provider_state(
                                    harness.session.session_id
                                ),
                                f"fault:{case}",
                            )
                        )
                    )
                self.assertFalse(result.recovered)
                self.assertEqual(
                    harness.store.get_session(harness.session.session_id).status,
                    "recovery_required",
                )
                self.assertIn(
                    harness.store.get_session(
                        harness.session.session_id
                    ).recovery_reason_code,
                    PUBLIC_RUNTIME_RECOVERY_REASON_CODES,
                )



if __name__ == "__main__":
    unittest.main()
