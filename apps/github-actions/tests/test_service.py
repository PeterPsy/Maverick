from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SERVICE_PATH = Path(__file__).resolve().parents[1] / "backend" / "service.py"
SPEC = importlib.util.spec_from_file_location("github_actions_service", SERVICE_PATH)
assert SPEC is not None and SPEC.loader is not None
SERVICE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SERVICE
SPEC.loader.exec_module(SERVICE)


class FakeGitHubActionsClient(SERVICE.GitHubActionsClient):
    def __init__(self, payload: dict[str, object]) -> None:
        credentials = SERVICE.GitHubAppCredentials("app", "installation", "private-key")
        super().__init__(credentials)
        self.payload = payload
        self.requested_path = ""

    def _request(self, method: str, path: str, *, body=None):
        self.requested_path = f"{method} {path}"
        return self.payload


class GitHubActionsServiceTest(unittest.TestCase):
    def test_run_jobs_returns_redacted_assignment_metadata(self) -> None:
        client = FakeGitHubActionsClient({
            "jobs": [{
                "id": 42,
                "name": "diagnostics",
                "status": "online",
                "conclusion": None,
                "started_at": "2026-09-21T12:00:00Z",
                "completed_at": None,
                "runner_name": "MacBook-Pro-6",
                "runner_group_name": "Default",
                "labels": ["self-hosted", "macOS", "ARM64"],
                "steps": [{"name": "secret detail that is intentionally excluded"}],
            }],
        })

        result = client.run_jobs({"repository": "giuntiocram/maverick-glasses-ios", "run_id": 99})

        self.assertEqual(
            client.requested_path,
            "GET /repos/giuntiocram/maverick-glasses-ios/actions/runs/99/jobs?filter=all&per_page=100",
        )
        self.assertEqual(result["action"], "run_jobs")
        self.assertEqual(result["jobs"], [{
            "id": 42,
            "name": "diagnostics",
            "status": "online",
            "conclusion": None,
            "started_at": "2026-09-21T12:00:00Z",
            "completed_at": None,
            "runner_name": "MacBook-Pro-6",
            "runner_group_name": "Default",
            "labels": ["self-hosted", "macOS", "ARM64"],
        }])

    def test_repository_and_dispatch_ref_are_explicit(self) -> None:
        with self.assertRaises(SERVICE.GitHubActionsError):
            SERVICE._repo({})
        with self.assertRaises(SERVICE.GitHubActionsError):
            SERVICE._required_ref({})
        self.assertEqual(SERVICE._required_ref({"ref": "loopino/phase1"}), "loopino/phase1")

    def test_manifest_declares_run_job_action(self) -> None:
        self.assertIn("run_jobs", SERVICE._manifest()["actions"])

    def test_custom_workflow_does_not_receive_install_defaults(self) -> None:
        inputs = SERVICE._workflow_inputs({
            "workflow_id": "pwa-physical-browser-smoke.yml",
            "inputs": {"browser": "safari"},
        })

        self.assertEqual(inputs, {"browser": "safari"})

    def test_install_workflow_defaults_to_build_only_without_targeting_a_device(self) -> None:
        inputs = SERVICE._workflow_inputs({"workflow_id": SERVICE.DEFAULT_WORKFLOW})

        self.assertEqual(inputs, {
            "build_only": "true",
            "launch_app": "false",
        })


if __name__ == "__main__":
    unittest.main()
