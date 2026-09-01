from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_factory import _tool_orchestrator
from core.runtime.hosted_agentic_policy import normalized_tool_result
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy
from core.runtime.tool_schema import provider_tool_name
from tests.support.hosted_agentic_harness import HostedAgenticHarness


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class HostedAgenticFactoryToolsTest(unittest.TestCase):
    def test_production_filesystem_result_markers_narrow_public_authority(
        self,
    ) -> None:
        harness = HostedAgenticHarness(self)
        workspace_root = harness.root / "workspaces" / "default"
        (workspace_root / "AGENTS.md").write_text(
            "Instruction SSN 123-45-6789\n",
            encoding="utf-8",
        )
        (workspace_root / "customer.txt").write_text(
            "customer SSN 123-45-6789\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        issued = issue_runtime_public_content_authority(
            state.workspace_store,
            workspace_id="default",
            actor_id="operator-fixture",
            expected_revision=0,
            now=NOW,
        )
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="admin",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id=harness.session.session_id,
            execution_mode="full-access",
        )
        orchestrator = _tool_orchestrator(
            SimpleNamespace(session=harness.session),
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=HostedToolProcessRegistry(store=state.runtime_store),
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                filesystem_read=True,
            ),
            allowed_tool_handles=(
                "core-capability:workspace.instructions",
                "core-capability:filesystem.search",
                "core-capability:filesystem.read",
            ),
            allowed_remote_data_classes=("public",),
            authority_digest="",
        )
        authority = replace(authority, authority_digest=canonical_digest(authority))

        policy = RuntimeToolConfirmationPolicy(
            policy_revision="filesystem-marker:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        scenarios = (
            (
                "core-capability:workspace.instructions",
                {"path": "customer.txt"},
            ),
            (
                "core-capability:filesystem.search",
                {"path": ".", "query": "123-45-6789"},
            ),
            ("core-capability:filesystem.read", {"path": "customer.txt"}),
        )
        for index, (handle, arguments) in enumerate(scenarios):
            with self.subTest(handle=handle):
                outcome = orchestrator.invoke_provider_tool(
                    provider_tool_name=provider_tool_name(handle),
                    provider_tool_call_id=f"call-sensitive-filesystem-{index}",
                    arguments=arguments,
                    authority=authority,
                    context=actor,
                    turn_id="turn-sensitive-filesystem",
                    policy=policy,
                )

                self.assertEqual(outcome.invocation.state, "succeeded")
                self.assertEqual(
                    outcome.invocation.result_data_class,
                    "regulated_or_customer_data",
                )
                self.assertEqual(
                    outcome.invocation.result_classification_authority_id,
                    issued.classification_id,
                )
                normalized, is_error = normalized_tool_result(
                    orchestrator,
                    outcome,
                    allowed_remote_data_classes=("public",),
                )
                self.assertTrue(is_error)
                self.assertEqual(
                    normalized,
                    {"error": "tool_result_egress_denied"},
                )

    def test_persisted_tool_result_revalidates_authority_before_egress(
        self,
    ) -> None:
        harness = HostedAgenticHarness(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        issued = issue_runtime_public_content_authority(
            state.workspace_store,
            workspace_id="default",
            actor_id="operator-fixture",
            expected_revision=0,
            now=NOW,
        )
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="admin",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id=harness.session.session_id,
            execution_mode="full-access",
        )
        orchestrator = _tool_orchestrator(
            SimpleNamespace(session=harness.session),
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=HostedToolProcessRegistry(store=state.runtime_store),
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                shell=True,
            ),
            allowed_tool_handles=("core-capability:shell.run",),
            allowed_remote_data_classes=("public",),
            authority_digest="",
        )
        authority = replace(authority, authority_digest=canonical_digest(authority))
        outcome = orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("core-capability:shell.run"),
            provider_tool_call_id="call-revoked-egress",
            arguments={
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf REVOCATION_PRIVATE_MARKER",
                ],
                "mutation_scopes": [],
            },
            authority=authority,
            context=actor,
            turn_id="turn-revoked-egress",
            policy=RuntimeToolConfirmationPolicy(
                policy_revision="revoked-egress:1",
                require_confirmation_for_mutating=False,
                require_confirmation_for_destructive=False,
                max_tool_result_bytes=262_144,
            ),
        )
        self.assertEqual(outcome.invocation.state, "succeeded")
        self.assertEqual(outcome.invocation.result_data_class, "public")
        self.assertEqual(
            outcome.invocation.result_classification_authority_id,
            issued.classification_id,
        )

        revoke_runtime_public_content_authority(
            state.workspace_store,
            workspace_id="default",
            actor_id="operator-fixture",
            expected_revision=issued.revision,
            reason="negative delayed egress probe",
            now=NOW,
        )
        normalized, is_error = normalized_tool_result(
            orchestrator,
            outcome,
            allowed_remote_data_classes=("public",),
        )

        self.assertTrue(is_error)
        self.assertEqual(normalized, {"error": "tool_result_egress_denied"})
        self.assertNotIn("REVOCATION_PRIVATE_MARKER", json.dumps(normalized))

    def test_production_preflight_denies_shell_mutation_before_effect(self) -> None:
        harness = HostedAgenticHarness(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="admin",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id="hosted-session",
            execution_mode="full-access",
        )
        context = SimpleNamespace(session=harness.session)
        orchestrator = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=HostedToolProcessRegistry(store=state.runtime_store),
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                shell=True,
            ),
            allowed_tool_handles=("core-capability:shell.run",),
            allowed_remote_data_classes=("public",),
            authority_digest="",
        )
        authority = replace(
            authority,
            authority_digest=canonical_digest(authority),
        )
        target = harness.root / "workspaces" / "default" / "must-not-exist.txt"

        outcome = orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("core-capability:shell.run"),
            provider_tool_call_id="call-preflight-shell",
            arguments={
                "argv": ["/bin/sh", "-c", "printf escaped > must-not-exist.txt"],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": "a" * 64,
                    }
                ],
            },
            authority=authority,
            context=actor,
            turn_id="turn-hosted",
            policy=RuntimeToolConfirmationPolicy(
                policy_revision="preflight-shell:1",
                require_confirmation_for_mutating=False,
                require_confirmation_for_destructive=False,
                max_tool_result_bytes=262_144,
            ),
        )

        self.assertEqual(outcome.invocation.state, "denied")
        self.assertEqual(
            outcome.invocation.failure_reason,
            "tool_result_egress_not_guaranteed",
        )
        self.assertFalse(target.exists())

    @staticmethod
    def _install_runtime_capture_turn(
        state,
        *,
        session,
        harness,
        input_text: str,
    ) -> None:
        state.runtime_store.insert_session(session)
        state.runtime_store.save_turn(
            replace(
                harness.store.get_turn("turn-hosted"),
                input_text=input_text,
            )
        )

    def _discover(
        self,
        surface,
        actor,
        *,
        collection: str,
        identity_field: str,
        identity: str,
    ) -> dict[str, object]:
        cursor = 0
        while True:
            result = surface.handler(
                {"cursor": cursor, "max_results": 50},
                actor,
                None,
            )
            for item in result.payload[collection]:
                if item[identity_field] == identity:
                    return {
                        **item,
                        "result_data_class": result.classification.data_class,
                    }
            next_cursor = result.payload["next_cursor"]
            if next_cursor is None:
                self.fail(f"{identity} was not exposed through {collection}")
            cursor = next_cursor


if __name__ == "__main__":
    unittest.main()
