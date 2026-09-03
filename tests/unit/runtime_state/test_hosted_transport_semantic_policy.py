from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_binding import canonical_digest
from core.runtime.provider_input_context import RuntimeProviderInputSource
from core.skills.models import SkillDefinition
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


def _with_current_digest(authority):
    authority = replace(authority, authority_digest="")
    return replace(authority, authority_digest=canonical_digest(authority))


class HostedTransportSemanticPolicyTest(unittest.TestCase):
    def test_live_data_policy_narrowing_after_lazy_refresh_blocks_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        live_policy = harness.policy
        refresh_calls = 0

        def refresh(_context):
            nonlocal live_policy, refresh_calls
            refresh_calls += 1
            if refresh_calls == 4:
                live_policy = replace(
                    live_policy,
                    allowed_remote_data_classes=(),
                )
            return harness.authority

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(
                client,
                policy_resolver=lambda _context: live_policy,
                authority_refresher=refresh,
                request_preflight=lambda _request, _credential: SimpleNamespace(
                    snapshot_digest="3" * 64
                ),
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=events.append,
        )

        self.assertEqual(refresh_calls, 4)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "egress_data_class_denied"}],
        )

    def test_live_catalog_policy_narrowing_after_lazy_refresh_blocks_transport(self) -> None:
        cases = (
            (
                "handle",
                False,
                lambda policy: replace(
                    policy,
                    tool_handle_mode="none",
                    allowed_tool_handles=(),
                ),
                "tool_not_authorized",
            ),
            (
                "surface",
                False,
                lambda policy: replace(policy, allowed_surface_kinds=()),
                "tool_capability_denied",
            ),
            (
                "capability_flag",
                True,
                lambda policy: replace(policy, allow_filesystem_list=False),
                "tool_capability_denied",
            ),
        )
        for name, filesystem_list, narrow, reason_code in cases:
            with self.subTest(name=name):
                harness = HostedAgenticHarness(
                    self,
                    filesystem_list=filesystem_list,
                )
                live_policy = harness.policy
                refresh_calls = 0

                def refresh(_context):
                    nonlocal live_policy, refresh_calls
                    refresh_calls += 1
                    if refresh_calls == 4:
                        live_policy = narrow(live_policy)
                    return harness.authority

                client = DeterministicFakeAgenticClient()
                events = []
                result = execute_runtime_turn(
                    session=harness.session,
                    provider=harness.provider,
                    input_text="Use only synthetic fixture data.",
                    agentic_adapter=harness.adapter(
                        client,
                        policy_resolver=lambda _context: live_policy,
                        authority_refresher=refresh,
                        request_preflight=lambda _request, _credential: SimpleNamespace(
                            snapshot_digest="2" * 64
                        ),
                    ),
                    provider_state=harness.store.get_provider_state("session-hosted"),
                    correlation_id="turn-hosted",
                    effective_authority=harness.authority,
                    event_sink=events.append,
                )

                self.assertEqual(refresh_calls, 4)
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(client.requests, [])
                self.assertEqual(
                    [
                        event.payload
                        for event in events
                        if event.event_type == "runtime.error"
                    ],
                    [{"reason_code": reason_code}],
                )

    def test_live_app_reference_surface_narrowing_blocks_lazy_transport(self) -> None:
        harness = HostedAgenticHarness(self)
        authority = _with_current_digest(replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                app_references=True,
            ),
        ))
        live_policy = replace(
            harness.policy,
            allowed_surface_kinds=(
                *harness.policy.allowed_surface_kinds,
                "app-interface",
            ),
        )
        refresh_calls = 0
        preflight_requests = []

        def refresh(_context):
            nonlocal live_policy, refresh_calls
            refresh_calls += 1
            if refresh_calls == 4:
                live_policy = replace(
                    live_policy,
                    allowed_surface_kinds=tuple(
                        surface
                        for surface in live_policy.allowed_surface_kinds
                        if surface != "app-interface"
                    ),
                )
            return authority

        def preflight(request, _credential):
            preflight_requests.append(request)
            return SimpleNamespace(snapshot_digest="1" * 64)

        client = DeterministicFakeAgenticClient()
        events = []
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Inspect the synthetic CRM reference.",
            input_sources=(
                RuntimeProviderInputSource(
                    "app-reference:crm:fixture",
                    "app_reference",
                    "application/json",
                    {"app_id": "crm", "entity_id": "fixture"},
                ),
            ),
            agentic_adapter=harness.adapter(
                client,
                policy_resolver=lambda _context: live_policy,
                authority_refresher=refresh,
                authority_revalidator=lambda _context, current: current,
                request_preflight=preflight,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=authority,
            event_sink=events.append,
        )

        self.assertEqual(refresh_calls, 4)
        self.assertEqual(len(preflight_requests), 1)
        self.assertIn(
            "app_reference",
            tuple(block.provenance for block in preflight_requests[0].content_blocks),
        )
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "runtime_authority_projection_changed"}],
        )

    def test_toolless_request_revalidates_live_semantic_capabilities(self) -> None:
        for with_skill in (False, True):
            with self.subTest(with_skill=with_skill):
                harness = HostedAgenticHarness(self, max_tool_calls=1)
                authority = harness.authority
                invoked_skills = None
                if with_skill:
                    skill_root = (
                        harness.root
                        / "workspaces"
                        / "default"
                        / "data"
                        / "skills"
                        / "skills"
                        / "transport-skill"
                    )
                    skill_root.mkdir(parents=True)
                    (skill_root / "SKILL.md").write_text(
                        "# Transport skill\n\nUse only the synthetic fixture.\n",
                        encoding="utf-8",
                    )
                    authority = _with_current_digest(replace(
                        authority,
                        allowed_capabilities=replace(
                            authority.allowed_capabilities,
                            skill_catalog=True,
                        ),
                    ))
                    invoked_skills = [
                        SkillDefinition(
                            skill_id="transport-skill",
                            local_skill_id="transport-skill",
                            name="Transport skill",
                            description="Synthetic transport fixture.",
                            source_root=str(skill_root),
                            owner_kind="workspace",
                            owner_id="default",
                            workspace_id="default",
                            status="available",
                        )
                    ]
                live_policy = harness.policy
                refresh_calls = 0
                preflight_requests = []

                def refresh(_context):
                    nonlocal live_policy, refresh_calls
                    refresh_calls += 1
                    if refresh_calls == 8:
                        live_policy = replace(
                            live_policy,
                            tool_handle_mode="none",
                            allowed_tool_handles=(),
                        )
                    return authority

                def preflight(request, _credential):
                    preflight_requests.append(request)
                    return SimpleNamespace(snapshot_digest="0" * 64)

                client = DeterministicFakeAgenticClient(
                    tool_name=harness.read_tool_name,
                )
                events = []
                result = execute_runtime_turn(
                    session=harness.session,
                    provider=harness.provider,
                    input_text="Use only synthetic fixture data.",
                    invoked_skills=invoked_skills,
                    agentic_adapter=harness.adapter(
                        client,
                        policy_resolver=lambda _context: live_policy,
                        authority_refresher=refresh,
                        authority_revalidator=lambda _context, current: current,
                        request_preflight=preflight,
                    ),
                    provider_state=harness.store.get_provider_state(
                        "session-hosted"
                    ),
                    correlation_id="turn-hosted",
                    effective_authority=authority,
                    event_sink=events.append,
                )

                self.assertEqual(refresh_calls, 8)
                self.assertEqual(len(preflight_requests), 2)
                self.assertEqual(preflight_requests[1].tool_definitions, ())
                self.assertEqual(
                    any(
                        block.provenance == "skill_fragment"
                        for block in preflight_requests[1].content_blocks
                    ),
                    with_skill,
                )
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(len(client.requests), 1)
                self.assertEqual(
                    [
                        event.payload
                        for event in events
                        if event.event_type == "runtime.error"
                    ],
                    [{"reason_code": "runtime_authority_projection_changed"}],
                )


if __name__ == "__main__":
    unittest.main()
