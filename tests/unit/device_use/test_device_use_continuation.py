from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.device_use.models import DeviceUseSessionBinding
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.service import configure_workspace_provider
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import admit_runtime_session
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from core.runtime.execution_binding import canonical_digest
from core.runtime.service import create_runtime_session, transition_runtime_session
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class DeviceUseContinuationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_repo_root(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            self.state = bootstrap_platform_state(
                start_path=self.root,
                now=NOW,
                install_builtin_apps=False,
            )
        configure_workspace_provider(
            self.state.provider_store,
            workspace_id="default",
            provider_id="codex",
            registry=self.state.provider_registry,
            now=NOW,
        )

    def _source_session(self, session_id: str, *, obsolete: bool = False):
        binding = build_pinned_execution_binding(
            self.state.provider_store,
            self.state.provider_registry,
            session_id=session_id,
            workspace_id="default",
            execution_mode="full-access",
            now=NOW,
        )
        if obsolete:
            binding = replace(
                binding,
                adapter_version="obsolete",
                binding_digest="",
            )
            binding = replace(binding, binding_digest=canonical_digest(binding))
        source = create_runtime_session(
            self.state.runtime_store,
            session_id=session_id,
            workspace_id="default",
            agent_id="chat",
            requested_mode="full-access",
            platform_allows_full_access=True,
            start_path=self.root,
            governance=self.state.workspace_store.get_governance("default"),
            execution_binding=binding,
            now=NOW,
        )
        return transition_runtime_session(
            self.state.runtime_store,
            session_id=source.session_id,
            target_status="running",
            now=NOW,
        )

    def test_obsolete_device_authority_never_forks_into_a_workspace_runtime(self) -> None:
        source = self._source_session("device-source", obsolete=True)
        source = self.state.runtime_store.save_session(replace(
            source,
            device_use_binding=DeviceUseSessionBinding(
                activation_id="01234567-89ab-cdef-0123-456789abcdef",
                workspace_id="default",
                owner_user_id="user-1",
                protocol_version="maverick.device-use.v1",
                executor_contract="macos-v41",
                tool_contract_digest="a" * 64,
                mode="on",
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
