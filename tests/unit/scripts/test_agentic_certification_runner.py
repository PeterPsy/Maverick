"""The operator runner separates collection, natural review, and signing."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_agentic_certification as runner
from scripts import manage_agentic_certification_budget as budget_runner
from tests.support.certification_budget import fixture_budget_environment


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
            for extra in (["--live-probe"], ["--live-probe", "--max-cost-microusd", "0"],
                          ["--live-probe", "--max-cost-microusd", "1000000"]):
                with self.assertRaises(SystemExit):
                    runner.main([*self.arguments(Path(folder) / "result.json"), *extra])
            execute.assert_not_called()

    def test_live_forwards_one_verified_shared_ledger(self):
        env = fixture_budget_environment(self)
        with tempfile.TemporaryDirectory() as folder, patch.object(
            runner, "execute_certification_suite", return_value=object(),
        ) as execute, patch.object(runner, "collection_to_json", return_value='{}'):
            runner.main([
                *self.arguments(Path(folder) / "result.json"), "--live-probe", "--max-cost-microusd", "1000000",
                "--budget-ledger", env["MAVERICK_CERTIFICATION_BUDGET_LEDGER"],
                "--budget-policy-digest", env["MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"],
            ])
            actual = execute.call_args.kwargs["environment"]
            for key in ("MAVERICK_CERTIFICATION_BUDGET_LEDGER", "MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"):
                self.assertEqual(actual[key], env[key])

    def test_p6_budget_cli_rejects_more_than_five_dollars_or_faster_google(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "budget.sqlite3"
            for extra in (["--openrouter-max-cost-microusd", "5000001"],
                          ["--google-min-interval-seconds", "14"]):
                with self.assertRaises(SystemExit):
                    budget_runner.main([
                        "--ledger", str(ledger), "create", "--authorization-ref", "a" * 64,
                        "--confirmation", "google-project-free-tier-confirmed", *extra,
                    ])
            self.assertFalse(ledger.exists())

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
