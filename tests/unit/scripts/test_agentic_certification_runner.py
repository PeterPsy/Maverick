"""The operator runner separates collection, natural review, and signing."""

from contextlib import redirect_stdout
import io
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
                self.assertEqual(execute.call_args.kwargs["failure_artifact_path"], output)
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

    def test_openrouter_live_collection_resolves_production_credential(self):
        env = fixture_budget_environment(self)
        with tempfile.TemporaryDirectory() as folder, patch.object(
            runner,
            "execute_certification_suite",
            return_value=object(),
        ) as execute, patch.object(
            runner,
            "collection_to_json",
            return_value="{}",
        ), patch(
            "core.providers.certification_natural_credential.production_openrouter_credential",
            return_value="leased-secret",
        ) as resolve:
            runner.main(
                [
                    "collect",
                    "--suite-id",
                    "maverick-openrouter-agentic-contract",
                    "--suite-version",
                    "68",
                    "--adapter-artifact-digest",
                    "a" * 64,
                    "--evidence-ref",
                    "platform-evidence:test",
                    "--output",
                    str(Path(folder) / "result.json"),
                    "--live-probe",
                    "--max-cost-microusd",
                    "1000000",
                    "--budget-ledger",
                    env["MAVERICK_CERTIFICATION_BUDGET_LEDGER"],
                    "--budget-policy-digest",
                    env["MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"],
                    "--openrouter-control-root",
                    folder,
                ]
            )

            resolve.assert_called_once_with(Path(folder).resolve())
            self.assertEqual(
                execute.call_args.kwargs["environment"]["MAVERICK_OPENROUTER_CERTIFICATION_API_KEY"],
                "leased-secret",
            )

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

    def test_p6_budget_cli_can_continue_an_openrouter_only_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            predecessor_path = root / "predecessor.sqlite3"
            predecessor = budget_runner.CertificationBudgetLedger.create(
                predecessor_path,
                authorization_ref="a" * 64,
                limits=(
                    budget_runner.CertificationBudgetLimit(
                        "openrouter",
                        "paid",
                        5_000_000,
                        1_000,
                        6,
                    ),
                ),
            )
            predecessor.halt("openrouter", reason="operator_stop")
            successor_path = root / "successor.sqlite3"

            output = io.StringIO()
            with redirect_stdout(output):
                result = budget_runner.main(
                    [
                        "--ledger",
                        str(successor_path),
                        "create-successor",
                        "--authorization-ref",
                        "b" * 64,
                        "--confirmation",
                        "successor-job-authorized",
                        "--predecessor-ledger",
                        str(predecessor_path),
                        "--predecessor-policy-digest",
                        predecessor.policy_digest,
                        "--openrouter-only",
                        "--openrouter-max-cost-microusd",
                        "5000000",
                        "--openrouter-max-requests",
                        "1000",
                        "--openrouter-min-interval-seconds",
                        "6",
                    ]
                )
            self.assertEqual(result, 0)
            policy_digest = json.loads(output.getvalue())["policy_digest"]
            status = budget_runner.CertificationBudgetLedger(
                successor_path,
                policy_digest=policy_digest,
            ).status()
            self.assertEqual(tuple(status), ("openrouter",))

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

    def test_natural_phases_delegate_to_the_code_owned_operator(self):
        with patch(
            "core.providers.certification_natural_operator.run_openrouter_natural_cli",
            return_value=7,
        ) as natural:
            self.assertEqual(runner.main(["natural", "--bounded"]), 7)
            natural.assert_called_once_with(["--bounded"])
        with patch(
            "core.providers.certification_natural_review.review_openrouter_natural_cli",
            return_value=8,
        ) as review:
            self.assertEqual(runner.main(["review-natural", "--bounded"]), 8)
            review.assert_called_once_with(["--bounded"])
        with patch(
            "core.providers.certification_openrouter_release_operator.activate_openrouter_release_cli",
            return_value=9,
        ) as activate:
            self.assertEqual(runner.main(["activate-openrouter", "--bounded"]), 9)
            activate.assert_called_once_with(["--bounded"])


if __name__ == "__main__":
    unittest.main()
