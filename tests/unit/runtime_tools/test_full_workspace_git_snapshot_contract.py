from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import subprocess
from threading import Event
import unittest
from unittest.mock import patch

from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceGitSnapshotContractTest(
    FullWorkspaceContractFixture,
    unittest.TestCase,
):
    def test_shell_snapshot_blocks_post_spawn_git_create_and_rename(self) -> None:
        capabilities = self._capabilities()
        for mutable in (False, True):
            with self.subTest(mutable=mutable):
                case = f"shell-{'cow' if mutable else 'read'}"
                command, mutation_scopes = self._race_case(
                    capabilities,
                    case=case,
                    mutable=mutable,
                )
                spawned = Event()
                real_popen = subprocess.Popen

                def observed_spawn(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    spawned.set()
                    return process

                with patch(
                    "core.runtime.hosted_workspace_shell.subprocess.Popen",
                    side_effect=observed_spawn,
                ):
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            capabilities["core-capability:shell.run"].handler,
                            {
                                "argv": ["/bin/sh", "-c", command],
                                "mutation_scopes": mutation_scopes,
                            },
                            self.context,
                            None,
                        )
                        self.assertTrue(spawned.wait(timeout=5))
                        self._create_and_rename_git(case)
                        result = future.result(timeout=10)
                payload = getattr(result, "payload", result)
                self.assertEqual(payload["exit_code"], 0)
                self.assertEqual(payload["output"], "SNAPSHOT-SAFE")
                if mutable:
                    self.assertEqual(
                        (self.workspace / f"{case}-committed.txt").read_text(
                            encoding="utf-8"
                        ),
                        "committed",
                    )

    def test_process_snapshot_blocks_post_spawn_git_create_and_rename(self) -> None:
        capabilities = self._capabilities(processes=True)
        for mutable in (False, True):
            with self.subTest(mutable=mutable):
                case = f"process-{'cow' if mutable else 'read'}"
                command, mutation_scopes = self._race_case(
                    capabilities,
                    case=case,
                    mutable=mutable,
                )
                started = capabilities["core-capability:process.start"].handler(
                    {
                        "argv": ["/bin/sh", "-c", command],
                        "mutation_scopes": mutation_scopes,
                    },
                    self.context,
                    None,
                )
                self._create_and_rename_git(case)
                status = self._wait_for_process(
                    capabilities,
                    str(started.payload["process_id"]),
                )
                self.assertEqual(status.payload["status"], "exited")
                self.assertEqual(status.payload["exit_code"], 0)
                self.assertEqual(status.payload["output"], "SNAPSHOT-SAFE")
                if mutable:
                    self.assertEqual(
                        (self.workspace / f"{case}-committed.txt").read_text(
                            encoding="utf-8"
                        ),
                        "committed",
                    )

    def _race_case(self, capabilities, *, case: str, mutable: bool):
        rename_parent = self.workspace / case / "rename"
        pending = rename_parent / "pending"
        pending.mkdir(parents=True)
        (pending / "private-marker").write_text(
            "LEAKED-GIT-METADATA",
            encoding="utf-8",
        )
        created_marker = f"/workspace/{case}/create/.git/private-marker"
        renamed_marker = f"/workspace/{case}/rename/.git/private-marker"
        write = (
            f"printf committed > {case}-committed.txt; "
            if mutable
            else ""
        )
        command = (
            "sleep 0.3; "
            f"if test -e {created_marker} || test -e {renamed_marker}; "
            "then printf LEAKED-GIT-METADATA; "
            f"else {write}printf SNAPSHOT-SAFE; fi"
        )
        if not mutable:
            return command, []
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        return command, [
            {
                "path": ".",
                "instruction_scope_digest": scope_digest,
            }
        ]

    def _create_and_rename_git(self, case: str) -> None:
        created = self.workspace / case / "create" / ".git"
        created.mkdir(parents=True)
        (created / "private-marker").write_text(
            "LEAKED-GIT-METADATA",
            encoding="utf-8",
        )
        rename_parent = self.workspace / case / "rename"
        (rename_parent / "pending").rename(rename_parent / ".git")


if __name__ == "__main__":
    unittest.main()
