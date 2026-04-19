"""Split tests from tests/test_phase11_observability.py."""

from __future__ import annotations

from tests.phase11_observability_helpers import *


class TestPhase11ObservabilityRoots(Phase11ObservabilityBase):
    """Focused test slice."""

    def test_application_bootstrap_creates_installation_log_roots(self) -> None:
        repo_root = self.make_repo_root()

        application = create_application(start_path=repo_root)

        self.assertEqual(application["status"], "initialized")
        self.assertTrue((repo_root / "logs" / "platform").is_dir())
        self.assertTrue((repo_root / "logs" / "runtime").is_dir())

    def test_workspace_export_manifest_excludes_logs_by_default(self) -> None:
        repo_root = self.make_repo_root()
        workspace_paths = ensure_default_workspace(start_path=repo_root)
        data_file = workspace_paths.data / "chat" / "db.sqlite"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_text("db", encoding="utf-8")
        log_file = workspace_paths.logs / "workspace" / "workspace-20260418.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("{}", encoding="utf-8")

        manifest = build_export_manifest(
            "default",
            workspace_paths.root,
            [data_file, log_file],
        )

        self.assertEqual([item.relative_path for item in manifest.files], ["data/chat/db.sqlite"])
