from __future__ import annotations

from pathlib import Path
import os
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from core.cli.command_registry import CliCommandRegistry
from core.api.platform_state import bootstrap_platform_state
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_agentic_factory import _tool_orchestrator
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
)
from core.runtime.public_content_authority import (
    build_runtime_public_content_authority_record,
)
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_errors import RuntimeToolError
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedWorkspaceEffectAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = HostedAgenticHarness(self)
        self.workspace = self.harness.root / "workspaces" / "default"
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="agent-1",
            platform_role="admin",
            workspace_role="admin",
            session_id="session-hosted",
            execution_mode="full-access",
        )

    def test_shell_and_process_classify_output_before_overlay_commit(self) -> None:
        authority = build_runtime_public_content_authority_record(
            workspace_id="default",
            actor_id="operator-1",
            active=True,
        )
        resolver = build_hosted_tool_result_admission_resolver(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
            public_content_authority_resolver=lambda workspace_id: (
                authority if workspace_id == "default" else None
            ),
        )
        capabilities = self._capabilities(resolver)
        scope_digest = self._scope_digest(capabilities)

        safe = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf safe > safe-shell.txt; printf ordinary",
                ],
                "mutation_scopes": [self._mutation_scope(scope_digest)],
            },
            self.context,
            None,
        )
        self.assertEqual(safe.classification.data_class, "public")
        self.assertEqual(
            (self.workspace / "safe-shell.txt").read_text(encoding="utf-8"),
            "safe",
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_egress_not_guaranteed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        (
                            "printf blocked > blocked-shell.txt; "
                            "printf 'customer SSN 123-45-6789'"
                        ),
                    ],
                    "mutation_scopes": [self._mutation_scope(scope_digest)],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "blocked-shell.txt").exists())

        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf blocked > blocked-process.txt; "
                        "printf 'customer SSN 123-45-6789'"
                    ),
                ],
                "mutation_scopes": [self._mutation_scope(scope_digest)],
            },
            self.context,
            None,
        )
        process_id = str(started.payload["process_id"])
        for _ in range(150):
            try:
                capabilities["core-capability:process.status"].handler(
                    {"process_id": process_id},
                    self.context,
                    None,
                )
            except RuntimeToolError as error:
                self.assertEqual(
                    error.reason_code,
                    "tool_result_egress_not_guaranteed",
                )
                break
            time.sleep(0.02)
        else:
            self.fail("sensitive process output did not stop overlay commit")
        self.assertFalse((self.workspace / "blocked-process.txt").exists())

    def test_revocation_after_result_classification_discards_shell_and_process_overlays(
        self,
    ) -> None:
        active = build_runtime_public_content_authority_record(
            workspace_id="default",
            actor_id="operator-1",
            active=True,
        )
        current = {"authority": active}
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
            public_content_authority_resolver=lambda _workspace_id: current[
                "authority"
            ],
        )
        resolved_once: set[str] = set()

        def revoke_after_first_result(handle, arguments, result, context):
            resolved = admission(handle, arguments, result, context)
            if handle not in resolved_once and handle in {
                "core-capability:shell.run",
                "core-capability:process.status",
            }:
                resolved_once.add(handle)
                prior = current["authority"]
                current["authority"] = build_runtime_public_content_authority_record(
                    workspace_id="default",
                    actor_id="operator-2",
                    active=False,
                    prior=prior,
                    expected_revision=prior.revision,
                )
            return resolved

        capabilities = self._capabilities(revoke_after_first_result)
        scope_digest = self._scope_digest(capabilities)
        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_egress_not_guaranteed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > revoked-shell.txt; printf ordinary",
                    ],
                    "mutation_scopes": [self._mutation_scope(scope_digest)],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "revoked-shell.txt").exists())

        current["authority"] = build_runtime_public_content_authority_record(
            workspace_id="default",
            actor_id="operator-3",
            active=True,
            prior=current["authority"],
            expected_revision=current["authority"].revision,
        )
        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf blocked > revoked-process.txt; printf ordinary",
                ],
                "mutation_scopes": [self._mutation_scope(scope_digest)],
            },
            self.context,
            None,
        )
        process_id = str(started.payload["process_id"])
        for _ in range(150):
            try:
                capabilities["core-capability:process.status"].handler(
                    {"process_id": process_id},
                    self.context,
                    None,
                )
            except RuntimeToolError as error:
                self.assertEqual(
                    error.reason_code,
                    "tool_result_egress_not_guaranteed",
                )
                break
            time.sleep(0.02)
        else:
            self.fail("authority revocation did not stop process overlay commit")
        self.assertFalse((self.workspace / "revoked-process.txt").exists())

    def test_revocation_during_shell_batch_commit_rolls_back_workspace_effects(
        self,
    ) -> None:
        active = build_runtime_public_content_authority_record(
            workspace_id="default",
            actor_id="operator-1",
            active=True,
        )
        current = {"authority": active}
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
            public_content_authority_resolver=lambda _workspace_id: current[
                "authority"
            ],
        )

        def revoke_after_commit(event, path):
            if event != "write_committed" or path not in {
                "rollback-shell.txt",
                "rollback-process.txt",
            }:
                return
            prior = current["authority"]
            current["authority"] = build_runtime_public_content_authority_record(
                workspace_id="default",
                actor_id="operator-2",
                active=False,
                prior=prior,
                expected_revision=prior.revision,
            )

        capabilities = self._capabilities(
            admission,
            filesystem_race_hook=revoke_after_commit,
        )
        scope_digest = self._scope_digest(capabilities)

        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_egress_not_guaranteed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf rollback > rollback-shell.txt; printf ordinary",
                    ],
                    "mutation_scopes": [self._mutation_scope(scope_digest)],
                },
                self.context,
                None,
            )

        self.assertFalse((self.workspace / "rollback-shell.txt").exists())

        current["authority"] = build_runtime_public_content_authority_record(
            workspace_id="default",
            actor_id="operator-3",
            active=True,
            prior=current["authority"],
            expected_revision=current["authority"].revision,
        )
        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf rollback > rollback-process.txt; printf ordinary",
                ],
                "mutation_scopes": [self._mutation_scope(scope_digest)],
            },
            self.context,
            None,
        )
        process_id = str(started.payload["process_id"])
        for _ in range(150):
            try:
                capabilities["core-capability:process.status"].handler(
                    {"process_id": process_id},
                    self.context,
                    None,
                )
            except RuntimeToolError as error:
                self.assertEqual(
                    error.reason_code,
                    "tool_result_egress_not_guaranteed",
                )
                break
            time.sleep(0.02)
        else:
            self.fail("revocation during process commit was not denied")
        self.assertFalse((self.workspace / "rollback-process.txt").exists())

    def test_production_create_is_public_after_orchestrator_rebuild(self) -> None:
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=self.harness.root,
                install_builtin_apps=False,
            )
        issue_runtime_public_content_authority(
            state.workspace_store,
            workspace_id=self.context.workspace_id,
            actor_id="operator-fixture",
            expected_revision=0,
        )
        runtime_context = SimpleNamespace(session=self.harness.session)
        first = self._production_orchestrator(
            state,
            runtime_context,
        )
        first_surfaces = {
            surface.definition.handle: surface
            for surface in first.catalog_builder.core_capabilities
        }
        instructions = first_surfaces[
            "core-capability:workspace.instructions"
        ].handler(
            {"path": "created-after-rebuild.txt"},
            self.context,
            None,
        )
        created = first_surfaces["core-capability:filesystem.write"].handler(
            {
                "path": "created-after-rebuild.txt",
                "content": "ordinary public content\n",
                "create_only": True,
                "instruction_scope_digest": instructions.payload[
                    "scope_digest"
                ],
            },
            self.context,
            None,
        )

        rebuilt = self._production_orchestrator(state, runtime_context)
        rebuilt_surfaces = {
            surface.definition.handle: surface
            for surface in rebuilt.catalog_builder.core_capabilities
        }
        reread = rebuilt_surfaces["core-capability:filesystem.read"].handler(
            {"path": "created-after-rebuild.txt"},
            self.context,
            None,
        )

        self.assertEqual(created.classification.data_class, "public")
        self.assertEqual(reread.classification.data_class, "public")
        self.assertEqual(reread.payload["content"], "ordinary public content\n")

    def _capabilities(self, resolver, *, filesystem_race_hook=None):
        surfaces = build_core_runtime_tool_capabilities(
            workspace_id="default",
            workspace_root=self.workspace,
            runtime_root=Path(self.harness.session.runtime_root),
            process_registry=HostedToolProcessRegistry(store=self.harness.store),
            result_classification_resolver=resolver,
            filesystem_race_hook=filesystem_race_hook,
        )
        return {surface.definition.handle: surface for surface in surfaces}

    def _production_orchestrator(self, state, runtime_context):
        return _tool_orchestrator(
            runtime_context,
            actor=self.context,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=HostedToolProcessRegistry(
                store=state.runtime_store,
            ),
        )

    def _scope_digest(self, capabilities) -> str:
        result = capabilities["core-capability:workspace.instructions"].handler(
            {"path": ".", "target_is_directory": True},
            self.context,
            None,
        )
        return str(result.payload["scope_digest"])

    @staticmethod
    def _mutation_scope(scope_digest: str) -> dict[str, str]:
        return {
            "path": ".",
            "instruction_scope_digest": scope_digest,
        }


if __name__ == "__main__":
    unittest.main()
