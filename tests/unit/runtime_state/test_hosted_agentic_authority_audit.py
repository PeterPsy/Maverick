"""Authority audit regressions for hosted agentic runtimes."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.agentic_adapter import RuntimeHealth
from core.runtime.authority_service import resolve_and_record_runtime_authority
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticAuthorityAuditTest(unittest.TestCase):
    def test_initial_audit_uses_adapter_tool_candidates(self) -> None:
        harness = HostedAgenticHarness(self)

        class Adapter:
            async def health(self, _context):
                return RuntimeHealth(status="healthy")

            def currently_authorized_tool_handles(self, _binding):
                return (
                    "core-capability:filesystem.list",
                    "core-capability:filesystem.read",
                )

        state = SimpleNamespace(
            provider_store=object(),
            runtime_store=object(),
            runtime_event_bus=None,
        )
        record = Mock()
        with patch(
            "core.runtime.authority_service.resolve_effective_runtime_authority",
            return_value=harness.authority,
        ) as resolve, patch(
            "core.runtime.authority_service.live_runtime_actor_policy",
            return_value=(True, "workspace-actor:test:1"),
        ), patch(
            "core.runtime.authority_service.record_runtime_event",
            record,
        ):
            resolve_and_record_runtime_authority(
                state,
                session=harness.session,
                adapter=Adapter(),
                turn_id="turn-hosted",
            )

        self.assertEqual(
            resolve.call_args.kwargs["currently_authorized_tool_handles"],
            (
                "core-capability:filesystem.list",
                "core-capability:filesystem.read",
            ),
        )
        self.assertEqual(
            record.call_args.kwargs["payload"]["allowed_tool_handle_count"],
            len(harness.authority.allowed_tool_handles),
        )


if __name__ == "__main__":
    unittest.main()
