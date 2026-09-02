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


def probe_workspace_git_metadata_masking() -> bool:
    """Snapshot-isolate Git metadata, including post-spawn create/rename races."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime_root = root / "runtime"
        runtime_root.mkdir()
        git_marker = root / ".git" / "private-marker"
        git_marker.parent.mkdir()
        git_marker.write_text("repository-private", encoding="utf-8")
        nested_marker = root / "project" / ".git" / "private-marker"
        nested_marker.parent.mkdir(parents=True)
        nested_marker.write_text("nested-repository-private", encoding="utf-8")
        worktree_pointer = root / "worktree" / ".git"
        worktree_pointer.parent.mkdir(parents=True)
        worktree_pointer.write_text(
            "gitdir: /platform/private/worktree\n",
            encoding="utf-8",
        )
        race = {"case": "", "observed": ""}

        def create_post_spawn_git(kind: str) -> None:
            case = race["case"]
            if not case:
                raise RuntimeError("workspace snapshot race case missing")
            created = root / case / "create" / ".git"
            created.mkdir(parents=True)
            (created / "private-marker").write_text(
                "LEAKED-GIT-METADATA",
                encoding="utf-8",
            )
            rename_parent = root / case / "rename"
            (rename_parent / "pending").rename(rename_parent / ".git")
            race["observed"] = kind

        process_registry = HostedToolProcessRegistry(
            store=_runtime_store(root, runtime_root),
            spawn_observer=create_post_spawn_git,
        )
        capabilities = {
            surface.definition.handle: surface
            for surface in build_core_runtime_tool_capabilities(
                workspace_id=_WORKSPACE_ID,
                workspace_root=root,
                runtime_root=runtime_root,
                process_registry=process_registry,
                workspace_spawn_observer=create_post_spawn_git,
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
        scopes = (
            [],
            [
                {
                    "path": ".",
                    "instruction_scope_digest": str(
                        instructions.payload["scope_digest"]
                    ),
                }
            ],
        )
        static_command = (
            "test ! -e /workspace/.git/private-marker && "
            "test ! -e /workspace/project/.git/private-marker && "
            "test ! -s /workspace/worktree/.git"
        )
        shell_payloads = []
        process_payloads = []
        for index, mutation_scopes in enumerate(scopes):
            shell_case = f"shell-race-{index}"
            _prepare_git_rename_race(root, shell_case)
            race["case"] = shell_case
            race["observed"] = ""
            command = (
                "sleep 0.1; "
                f"{static_command} && "
                f"test ! -e /workspace/{shell_case}/create/.git/private-marker && "
                f"test ! -e /workspace/{shell_case}/rename/.git/private-marker && "
                "printf masked"
            )
            shell = capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/sh", "-c", command],
                    "mutation_scopes": mutation_scopes,
                },
                context,
                None,
            )
            shell_payloads.append(getattr(shell, "payload", shell))
            if race["observed"] != "shell":
                return False
            process_case = f"process-race-{index}"
            _prepare_git_rename_race(root, process_case)
            race["case"] = process_case
            race["observed"] = ""
            command = (
                "sleep 0.1; "
                f"{static_command} && "
                f"test ! -e /workspace/{process_case}/create/.git/private-marker && "
                f"test ! -e /workspace/{process_case}/rename/.git/private-marker && "
                "printf masked"
            )
            started = capabilities["core-capability:process.start"].handler(
                {
                    "argv": ["/bin/sh", "-c", command],
                    "mutation_scopes": mutation_scopes,
                },
                context,
                None,
            )
            if race["observed"] != "process":
                return False
            process_id = str(getattr(started, "payload", started)["process_id"])
            process_payload = None
            for _attempt in range(150):
                status = capabilities["core-capability:process.status"].handler(
                    {"process_id": process_id},
                    context,
                    None,
                )
                process_payload = getattr(status, "payload", status)
                if process_payload["status"] == "exited":
                    break
                time.sleep(0.01)
            process_payloads.append(process_payload)
        return bool(
            len(shell_payloads) == len(process_payloads) == 2
            and all(
                payload["exit_code"] == 0 and payload["output"] == "masked"
                for payload in shell_payloads
            )
            and all(
                payload is not None
                and payload["status"] == "exited"
                and payload["exit_code"] == 0
                and payload["output"] == "masked"
                for payload in process_payloads
            )
        )


def _prepare_git_rename_race(root: Path, case: str) -> None:
    pending = root / case / "rename" / "pending"
    pending.mkdir(parents=True)
    (pending / "private-marker").write_text(
        "LEAKED-GIT-METADATA",
        encoding="utf-8",
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


__all__ = [
    "probe_workspace_effect_revocation_rollback",
    "probe_workspace_git_metadata_masking",
]
