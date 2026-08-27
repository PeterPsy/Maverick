"""Privilege-separation contract for protected OpenDesign store mutations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact_operations import (  # noqa: E402
    ArtifactStoreError,
    _authority_web_submission,
    run_artifact_operation,
)


class OpenDesignArtifactAuthorityTests(unittest.TestCase):
    def test_web_submission_handoff_rejects_a_mutable_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-authority-candidate-") as temp_dir:
            candidate = Path(temp_dir) / "candidate"
            candidate.mkdir()
            (candidate / "index.html").write_text("mutable", encoding="utf-8")
            with self.assertRaises(ArtifactStoreError) as raised:
                with _authority_web_submission(candidate):
                    self.fail("mutable submission unexpectedly crossed the authority boundary")
        self.assertEqual(raised.exception.code, "artifact_permissions_invalid")

    def test_mutation_is_delegated_without_exposing_host_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-authority-client-") as temp_dir:
            repository = self._repository(Path(temp_dir))
            expected = {
                "schema_version": "1",
                "operation": "repair",
                "status": "ready",
                "store_generation": "a" * 32,
                "runtime_artifact_sha256": "b" * 64,
                "web_overlay_sha256": "c" * 64,
                "data_generation_bootstrapped": False,
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"ok": True, "result": expected}),
                stderr="",
            )
            with (
                patch("opendesign_artifact_operations._is_artifact_authority", return_value=False),
                patch(
                    "opendesign_artifact_operations._validated_authority_command",
                    return_value=Path("/usr/local/libexec/maverick-opendesign-artifact-authority"),
                ),
                patch("opendesign_artifact_operations.shutil.which", return_value="/usr/bin/sudo"),
                patch("opendesign_artifact_operations.subprocess.run", return_value=completed) as invoked,
                patch(
                    "opendesign_artifact_operations._bootstrap_after_authority",
                    return_value={**expected, "data_generation_bootstrapped": True},
                ) as bootstrapped,
            ):
                result = run_artifact_operation(
                    "repair",
                    data_root=repository / "workspaces/acme/data/design-studio",
                    workspace_id="acme",
                    repository_root=repository,
                    auto=True,
                    audit_workers=2,
                )

            self.assertEqual(result, {**expected, "data_generation_bootstrapped": True})
            bootstrapped.assert_called_once()
            request = json.loads(invoked.call_args.kwargs["input"])
            self.assertEqual(
                request,
                {
                    "schema_version": "1",
                    "operation": "repair",
                    "workspace_id": "acme",
                    "auto": True,
                    "audit_workers": 2,
                    "candidate_path": None,
                    "candidate_digest": None,
                },
            )
            self.assertNotIn(str(repository), invoked.call_args.kwargs["input"])

    def test_signed_web_submission_delegates_only_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-authority-client-") as temp_dir:
            repository = self._repository(Path(temp_dir))
            candidate = Path(temp_dir) / "candidate"
            candidate.mkdir()
            private_file = candidate / "index.html"
            private_file.write_text("verified candidate", encoding="utf-8")
            private_file.chmod(0o444)
            candidate.chmod(0o555)
            digest = "d" * 64
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "schema_version": "1",
                            "operation": "publish-web",
                            "status": "ready",
                            "store_generation": "a" * 32,
                            "web_overlay_sha256": digest,
                        },
                    }
                ),
                stderr="",
            )
            observed_submission: dict[str, object] = {}

            def invoke(_command, **kwargs):
                request = json.loads(kwargs["input"])
                submitted = Path(request["candidate_path"])
                observed_submission["path"] = submitted
                observed_submission["content"] = (submitted / "index.html").read_text(
                    encoding="utf-8"
                )
                observed_submission["mode"] = (submitted / "index.html").stat().st_mode & 0o777
                return completed

            with (
                patch("opendesign_artifact_operations._is_artifact_authority", return_value=False),
                patch(
                    "opendesign_artifact_operations._validated_authority_command",
                    return_value=Path("/usr/local/libexec/maverick-opendesign-artifact-authority"),
                ),
                patch("opendesign_artifact_operations.shutil.which", return_value="/usr/bin/sudo"),
                patch("opendesign_artifact_operations.subprocess.run", side_effect=invoke) as invoked,
            ):
                result = run_artifact_operation(
                    "publish-web",
                    data_root=repository / "workspaces/acme/data/design-studio",
                    workspace_id="acme",
                    repository_root=repository,
                    candidate_path=candidate,
                    candidate_digest=digest,
                )

            request = json.loads(invoked.call_args.kwargs["input"])
            self.assertNotEqual(request["candidate_path"], str(candidate))
            self.assertTrue(
                str(request["candidate_path"]).startswith(
                    "/var/tmp/maverick-opendesign-submission-"
                )
            )
            self.assertFalse(Path(str(request["candidate_path"])).exists())
            self.assertEqual(observed_submission["content"], "verified candidate")
            self.assertEqual(observed_submission["mode"], 0o444)
            self.assertEqual(request["candidate_digest"], digest)
            self.assertNotIn("candidate_path", json.dumps(result))
            candidate.chmod(0o755)
            private_file.chmod(0o644)

    def test_authority_failure_is_redacted_and_typed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-authority-client-") as temp_dir:
            repository = self._repository(Path(temp_dir))
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=json.dumps(
                    {
                        "ok": False,
                        "error_code": "artifact_integrity_mismatch",
                        "phase": "artifact_full_verify",
                    }
                ),
                stderr="sensitive host detail",
            )
            with (
                patch("opendesign_artifact_operations._is_artifact_authority", return_value=False),
                patch(
                    "opendesign_artifact_operations._validated_authority_command",
                    return_value=Path("/usr/local/libexec/maverick-opendesign-artifact-authority"),
                ),
                patch("opendesign_artifact_operations.shutil.which", return_value="/usr/bin/sudo"),
                patch("opendesign_artifact_operations.subprocess.run", return_value=completed),
                self.assertRaises(ArtifactStoreError) as raised,
            ):
                run_artifact_operation(
                    "verify",
                    data_root=repository / "workspaces/acme/data/design-studio",
                    workspace_id="acme",
                    repository_root=repository,
                )

            self.assertEqual(raised.exception.code, "artifact_integrity_mismatch")
            self.assertEqual(raised.exception.phase, "artifact_full_verify")
            self.assertNotIn("sensitive", str(raised.exception))

    @staticmethod
    def _repository(parent: Path) -> Path:
        root = parent / "maverick"
        for name in ("apps", "core", "workspaces"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "AGENTS.md").write_text("", encoding="utf-8")
        return root


if __name__ == "__main__":
    unittest.main()
