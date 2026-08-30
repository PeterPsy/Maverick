from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_factory import _tool_orchestrator
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.app_reference_classification import (
    observe_runtime_app_reference,
)
from core.runtime.app_references import input_text_with_app_references
from core.runtime.provider_input_context import runtime_provider_input_sources
from core.runtime.provider_input_admission import (
    RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.workspaces.data_governance import WorkspaceResourceClassification
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class HostedAgenticFactoryToolsTest(unittest.TestCase):
    def test_production_composition_dispatches_and_continues_after_tool_result(self) -> None:
        harness = HostedAgenticHarness(self, filesystem_list=True)
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
        self.assertTrue(callable(state.runtime_input_classification_resolver))
        production_adapter = state.provider_registry.get_agentic_runtime_adapter(
            "maverick-tool-loop"
        )
        # Use the request builder selected by platform_state, not the harness
        # classifier called out by the P4 review.  Input classification comes
        # from the server-owned admission resolver and the continuation result
        # inherits the exact observed workspace resource classification.
        harness.request_builder = production_adapter.loop.request_builder
        client = DeterministicFakeAgenticClient(
            tool_name=harness.filesystem_list_tool_name,
            tool_arguments={"path": ".", "max_depth": 1},
        )
        self._classify_runtime_input(
            state,
            session=harness.session,
            turn_id="turn-hosted",
            source_id="turn-prompt",
            content="Use the public fixture tool and finish.",
        )
        input_sources = runtime_provider_input_sources(
            state,
            session=harness.session,
            turn_id="turn-hosted",
            input_text="Use the public fixture tool and finish.",
            app_references=None,
            attachments=None,
        )

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use the public fixture tool and finish.",
            agentic_adapter=harness.adapter(client),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            input_sources=input_sources,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertGreaterEqual(len(client.requests), 2)
        invocation = harness.store.list_tool_invocations(
            session_id="session-hosted"
        )[0]
        self.assertEqual(invocation.state, "succeeded")
        self.assertEqual(invocation.result_data_class, "public")

    def test_production_app_reference_resolver_uses_exact_workspace_record(self) -> None:
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
        self.assertTrue(
            callable(state.runtime_app_reference_classification_resolver)
        )
        reference = {
            "type": "entity",
            "app_id": "records",
            "entity_type": "record",
            "entity_id": "record-1",
            "label": "Public fixture",
            "summary": "Server-materialized public reference.",
        }
        observation = observe_runtime_app_reference(
            workspace_id="default",
            reference=reference,
        )
        state.workspace_store.save_resource_classification(
            WorkspaceResourceClassification(
                classification_id="classification-app-reference-1",
                workspace_id=observation.workspace_id,
                resource_kind=observation.resource_kind,
                resource_ref=observation.resource_ref,
                resource_identity=observation.resource_identity,
                resource_revision=observation.resource_revision,
                resource_digest=observation.resource_digest,
                data_class="public",
                trust_level="untrusted_external",
                revision=1,
                classified_by_actor_id="fixture-classifier",
                classified_at=NOW,
                updated_at=NOW,
            ),
            expected_revision=0,
        )
        self._classify_runtime_input(
            state,
            session=harness.session,
            turn_id="turn-hosted",
            source_id="turn-prompt",
            content="Inspect the public record.",
        )
        self._classify_runtime_input(
            state,
            session=harness.session,
            turn_id="turn-hosted",
            source_id="app-reference:0:metadata",
            content=input_text_with_app_references(
                input_text="",
                app_references=[reference],
            ).strip(),
        )
        sources = runtime_provider_input_sources(
            state,
            session=harness.session,
            turn_id="turn-hosted",
            input_text="Inspect the public record.",
            app_references=[reference],
            attachments=None,
        )
        app_source = next(
            source for source in sources if source.provenance == "app_reference"
        )
        self.assertEqual(app_source.classification.data_class, "public")

        production_adapter = state.provider_registry.get_agentic_runtime_adapter(
            "maverick-tool-loop"
        )
        harness.request_builder = production_adapter.loop.request_builder
        client = DeterministicFakeAgenticClient()
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                app_references=True,
            ),
            authority_digest="",
        )
        authority = replace(
            authority,
            authority_digest=canonical_digest(authority),
        )
        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Inspect the public record.",
            agentic_adapter=harness.adapter(
                client,
                authority_refresher=lambda _context: authority,
            ),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=authority,
            input_sources=sources,
        )

        self.assertEqual(result.exit_code, 0, repr(result))
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(
            any(
                block.provenance == "app_reference"
                and block.data_class == "public"
                for block in client.requests[0].content_blocks
            )
        )

    def test_official_cli_and_mcp_registries_are_discovered_and_invoked(self) -> None:
        root = make_temp_repo_root(self)
        workspace_root = root / "workspaces" / "default"
        runtime_root = workspace_root / "runtime"
        runtime_root.mkdir(parents=True)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=root,
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
        context = SimpleNamespace(
            session=SimpleNamespace(
                workspace_id="default",
                workspace_root=str(workspace_root),
                runtime_root=str(runtime_root),
            )
        )
        orchestrator = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=HostedToolProcessRegistry(store=state.runtime_store),
        )
        surfaces = {
            item.definition.handle: item
            for item in orchestrator.catalog_builder.core_capabilities
        }

        cli_entry = self._discover(
            surfaces["core-capability:cli.list"],
            actor,
            collection="commands",
            identity_field="command_id",
            identity="developer-context.list",
        )
        self.assertEqual(cli_entry["result_data_class"], "unclassified")
        cli_result = surfaces["core-capability:cli.run"].handler(
            {
                "command_id": "developer-context.list",
                "invocation_token": cli_entry["invocation_token"],
                "arguments": {},
            },
            actor,
            None,
        )
        self.assertEqual(
            cli_result.payload["command_id"],
            "developer-context.list",
        )
        self.assertEqual(cli_result.classification.data_class, "public")

        mcp_entry = self._discover(
            surfaces["core-capability:mcp.list"],
            actor,
            collection="tools",
            identity_field="tool_name",
            identity="developer-context.list",
        )
        self.assertEqual(mcp_entry["result_data_class"], "public")
        mcp_result = surfaces["core-capability:mcp.call"].handler(
            {
                "tool_name": "developer-context.list",
                "invocation_token": mcp_entry["invocation_token"],
                "arguments": {},
            },
            actor,
            None,
        )
        self.assertIn("items", mcp_result.payload)
        self.assertEqual(mcp_result.classification.data_class, "public")
        self.assertIsNotNone(
            orchestrator.catalog_builder.result_classification_resolver
        )

    @staticmethod
    def _classify_runtime_input(
        state,
        *,
        session,
        turn_id: str,
        source_id: str,
        content: object,
    ) -> None:
        digest = hashlib.sha256(canonical_egress_content(content)).hexdigest()
        source_ref = f"runtime-turn:{turn_id}:{source_id}"
        state.workspace_store.save_resource_classification(
            WorkspaceResourceClassification(
                classification_id=(
                    f"classification-{session.session_id}-{turn_id}-{source_id}"
                ),
                workspace_id=session.workspace_id,
                resource_kind=RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
                resource_ref=source_ref,
                resource_identity=(
                    f"runtime-input:{session.workspace_id}:{session.session_id}:"
                    f"{turn_id}:{source_id}:{digest}"
                ),
                resource_revision=digest,
                resource_digest=digest,
                data_class="public",
                trust_level="trusted_actor",
                revision=1,
                classified_by_actor_id="fixture-classifier",
                classified_at=NOW,
                updated_at=NOW,
            ),
            expected_revision=0,
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
