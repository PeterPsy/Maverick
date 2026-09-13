from __future__ import annotations

from dataclasses import replace
import unittest

from core.device_use.models import DeviceUseSessionBinding
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import admit_runtime_session
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from tests.support.continuation import NOW, RuntimeContinuationFixture


class DeviceUseContinuationTestCase(RuntimeContinuationFixture, unittest.TestCase):
    def test_obsolete_device_authority_never_forks_into_a_workspace_runtime(self) -> None:
        source = self._source_session("device-source")
        source = self.state.runtime_store.save_session(replace(
            source,
            device_use_binding=DeviceUseSessionBinding(
                activation_id="01234567-89ab-cdef-0123-456789abcdef",
                workspace_id="default",
                owner_user_id="user-1",
                protocol_version="maverick.device-use.v1",
                executor_contract="macos-v40",
                tool_contract_digest="a" * 64,
                initial_app="com.apple.Safari",
                approved_apps=("com.apple.Safari",),
                created_at=NOW,
            ),
        ))

        assessment = assess_runtime_session_admission(
            self.state.provider_store,
            self.state.runtime_store,
            self.state.provider_registry,
            session=source,
            target_session_id="must-not-exist",
            now=NOW,
        )
        self.assertEqual(assessment.status, "upgrade_required")
        self.assertEqual(assessment.detail_code, "device_use_continuation_unsupported")
        with self.assertRaises(RuntimeProfileUpgradeRequiredError) as caught:
            admit_runtime_session(self.state, session=source, now=NOW)
        self.assertEqual(caught.exception.reason_code, "runtime_profile_upgrade_required")
        self.assertEqual(caught.exception.detail_code, "device_use_continuation_unsupported")
        self.assertEqual(len(self.state.runtime_store.list_all_sessions()), 1)
