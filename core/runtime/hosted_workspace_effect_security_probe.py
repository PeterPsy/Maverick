"""Production-composed revocation probe for hosted workspace-effect commit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import time

from core.cli.command_registry import CliCommandRegistry
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
)
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.public_content_authority import (
    build_runtime_public_content_authority_record,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_errors import RuntimeToolError
from core.shared.in_memory_collection import InMemoryCollection


_PROBE_TIME = datetime(2026, 9, 1, tzinfo=UTC)
_WORKSPACE_ID = "hosted-workspace-effect-security-probe"


def probe_workspace_effect_revocation_rollback() -> bool:
    """Revoke during a real shell overlay commit and require full rollback."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime_root = root / "runtime"
        runtime_root.mkdir()
        current = {
            "record": build_runtime_public_content_authority_record(
                workspace_id=_WORKSPACE_ID,
                actor_id="core-security-probe",
                active=True,
                now=_PROBE_TIME,
            )
        }
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
            public_content_authority_resolver=lambda _workspace_id: current[
                "record"
            ],
        )
        crossed_commits: set[str] = set()

        def revoke_after_commit(event: str, path: str) -> None:
            if event != "write_committed" or path not in {
                "rollback-shell.txt",
                "rollback-process.txt",
            }:
                return
            crossed_commits.add(path)
            prior = current["record"]
            current["record"] = build_runtime_public_content_authority_record(
                workspace_id=_WORKSPACE_ID,
                actor_id="core-security-probe",
                active=False,
                prior=prior,
                expected_revision=prior.revision,
                now=_PROBE_TIME,
            )

        capabilities = {
            surface.definition.handle: surface
            for surface in build_core_runtime_tool_capabilities(
                workspace_id=_WORKSPACE_ID,
                workspace_root=root,
                runtime_root=runtime_root,
                process_registry=HostedToolProcessRegistry(
                    store=_runtime_store(root, runtime_root)
                ),
                result_classification_resolver=admission,
                filesystem_race_hook=revoke_after_commit,
            )
        }
        context = RuntimeToolActorContext(
            workspace_id=_WORKSPACE_ID,
            actor_id="core-security-probe",
            agent_id="core-security-probe",
            platform_role="admin",
            workspace_role="owner",
            session_id="security-probe-session",
            execution_mode="full-access",
        )
        instructions = capabilities[
            "core-capability:workspace.instructions"
        ].handler(
            {"path": ".", "target_is_directory": True},
            context,
            None,
        )
        try:
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                    "/bin/sh",
                    "-c",
                    "printf rollback > rollback-shell.txt; printf ordinary",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": str(
                                instructions.payload["scope_digest"]
                            ),
                        }
                    ],
                },
                context,
                None,
            )
        except RuntimeToolError as error:
            shell_denied = (
                error.reason_code == "tool_result_egress_not_guaranteed"
            )
        else:
            shell_denied = False

        prior = current["record"]
        current["record"] = build_runtime_public_content_authority_record(
            workspace_id=_WORKSPACE_ID,
            actor_id="core-security-probe",
            active=True,
            prior=prior,
            expected_revision=prior.revision,
            now=_PROBE_TIME,
        )
        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf rollback > rollback-process.txt; printf ordinary",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": str(
                            instructions.payload["scope_digest"]
                        ),
                    }
                ],
            },
            context,
            None,
        )
        process_denied = False
        for _attempt in range(150):
            try:
                capabilities["core-capability:process.status"].handler(
                    {"process_id": str(started.payload["process_id"])},
                    context,
                    None,
                )
            except RuntimeToolError as error:
                process_denied = (
                    error.reason_code
                    == "tool_result_egress_not_guaranteed"
                )
                break
            time.sleep(0.01)
        return bool(
            crossed_commits
            == {"rollback-shell.txt", "rollback-process.txt"}
            and shell_denied
            and process_denied
            and current["record"].data_class == "unclassified"
            and not (root / "rollback-shell.txt").exists()
            and not (root / "rollback-process.txt").exists()
        )


def _runtime_store(
    workspace_root: Path,
    runtime_root: Path,
) -> RuntimeDocumentStore:
    collection = InMemoryCollection
    store = RuntimeDocumentStore(
        RuntimeCollections(
            sessions=collection(),
            turns=collection(),
            events=collection(),
            processes=collection(),
            states=collection(),
            threads=collection(),
            tool_invocations=collection(),
            tool_confirmation_grants=collection(),
        )
    )
    store.insert_session(
        RuntimeSessionRecord(
            session_id="security-probe-session",
            workspace_id=_WORKSPACE_ID,
            agent_id="core-security-probe",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root=str(workspace_root),
            workdir=str(workspace_root),
            runtime_root=str(runtime_root),
            started_at=_PROBE_TIME,
            updated_at=_PROBE_TIME,
            ended_at=None,
            last_progress_at=_PROBE_TIME,
        )
    )
    return store


__all__ = ["probe_workspace_effect_revocation_rollback"]
