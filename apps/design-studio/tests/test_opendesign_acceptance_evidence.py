"""Evidence freshness and raw performance verification proofs."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_acceptance_evidence import (  # noqa: E402
    build_source_attestation,
    validate_source_attestation,
)


class OpenDesignAcceptanceEvidenceTests(unittest.TestCase):
    def test_source_attestation_ignores_only_evidence_outputs_and_rejects_code_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-evidence-") as temporary:
            repository = Path(temporary)
            source = repository / "core/runtime.py"
            evidence = (
                repository
                / "apps/design-studio/service/opendesign_product_acceptance_0_16_1.json"
            )
            source.parent.mkdir(parents=True)
            evidence.parent.mkdir(parents=True)
            source.write_text("READY = True\n", encoding="utf-8")
            evidence.write_text("{}\n", encoding="utf-8")
            self._git(repository, "init")
            self._git(repository, "config", "user.email", "evidence@example.invalid")
            self._git(repository, "config", "user.name", "Evidence Test")
            self._git(repository, "add", ".")
            self._git(repository, "commit", "-m", "fixture")

            original = build_source_attestation(repository)
            self.assertTrue(original["working_tree_clean"])
            validate_source_attestation(original, repository_root=repository)

            evidence.write_text('{"status":"passed"}\n', encoding="utf-8")
            evidence_only = build_source_attestation(repository)
            self.assertEqual(evidence_only["sha256"], original["sha256"])
            self.assertTrue(evidence_only["working_tree_clean"])

            source.write_text("READY = False\n", encoding="utf-8")
            modified = build_source_attestation(repository)
            self.assertNotEqual(modified["sha256"], original["sha256"])
            self.assertFalse(modified["working_tree_clean"])
            with self.assertRaisesRegex(ValueError, "stale|modified"):
                validate_source_attestation(original, repository_root=repository)

    @staticmethod
    def _git(repository: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    unittest.main()
