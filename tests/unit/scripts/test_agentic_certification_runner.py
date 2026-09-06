"""The operator runner separates collection, natural review, and signing."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_agentic_certification as runner


class AgenticCertificationRunnerTest(unittest.TestCase):
    def arguments(self, output):
        return ["collect", "--suite-id", "suite", "--suite-version", "40",
                "--adapter-artifact-digest", "a" * 64,
                "--evidence-ref", "platform-evidence:test", "--output", str(output)]

    def test_collection_defaults_to_no_live_and_cannot_sign(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "collection.json"
            with patch.dict("os.environ", {"MAVERICK_CERTIFICATION_ALLOW_LIVE": "1"}), patch.object(
                runner, "execute_certification_suite", return_value=object(),
            ) as execute, patch.object(runner, "collection_to_json", return_value='{"signed": false}'), patch.object(
                runner, "sign_certification_run",
            ) as sign:
                self.assertEqual(runner.main(self.arguments(output)), 0)
                self.assertEqual(execute.call_args.kwargs["step_kinds"], ("fixture_contract",))
                self.assertEqual(execute.call_args.kwargs["environment"]["MAVERICK_CERTIFICATION_ALLOW_LIVE"], "0")
                sign.assert_not_called()
            self.assertFalse(json.loads(output.read_text())["signed"])

    def test_live_requires_explicit_positive_budget_before_execution(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, "execute_certification_suite") as execute:
            for extra in (["--live-probe"], ["--live-probe", "--max-cost-microusd", "0"]):
                with self.assertRaises(SystemExit):
                    runner.main([*self.arguments(Path(folder) / "result.json"), *extra])
            execute.assert_not_called()

    def test_failure_never_creates_an_artifact_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"
            with patch.object(runner, "execute_certification_suite", side_effect=RuntimeError("fixture failed")):
                with self.assertRaises(RuntimeError):
                    runner.main(self.arguments(output))
            self.assertFalse(output.exists())
            output.write_text("preserve")
            with patch.object(runner, "execute_certification_suite") as execute, self.assertRaises(SystemExit):
                runner.main(self.arguments(output))
            self.assertEqual(output.read_text(), "preserve")
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
