"""Antigravity live-probe authority ordering without provider traffic."""

from __future__ import annotations

import asyncio
from unittest import mock
import unittest

from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.errors import CapabilityCertificateError
from core.providers.native_runtime_artifact import ANTIGRAVITY_CLI_RUNTIME_ARTIFACT
from scripts import run_antigravity_native_probe as probe
from tests.support.certification_budget import fixture_budget_environment


class AntigravityNativeProbeTest(unittest.TestCase):
    def test_live_opt_in_is_required_before_local_or_provider_work(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
            probe,
            "inspect_native_runtime_artifact",
        ) as inspect:
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_live_opt_in_required",
            ):
                asyncio.run(probe._probe())
        inspect.assert_not_called()

    def test_budget_is_reserved_before_catalog_egress_and_failure_halts(self) -> None:
        environment = {
            **fixture_budget_environment(self),
            "MAVERICK_CERTIFICATION_ALLOW_LIVE": "1",
            "MAVERICK_CERTIFICATION_MAX_COST_MICROUSD": "3500000",
        }
        observed_requests = []

        def unavailable_catalog(*_args, **_kwargs):
            ledger = CertificationBudgetLedger(
                environment["MAVERICK_CERTIFICATION_BUDGET_LEDGER"],
                policy_digest=environment[
                    "MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"
                ],
            )
            observed_requests.append(
                ledger.status()["google-ai-studio"]["requests"]
            )
            return None

        with mock.patch.dict("os.environ", environment, clear=True), mock.patch.object(
            probe,
            "inspect_native_runtime_artifact",
            return_value=ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
        ), mock.patch.object(
            probe,
            "discover_antigravity_native_catalog",
            side_effect=unavailable_catalog,
        ):
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "native_agent_model_unavailable",
            ):
                asyncio.run(probe._probe())

        ledger = CertificationBudgetLedger(
            environment["MAVERICK_CERTIFICATION_BUDGET_LEDGER"],
            policy_digest=environment[
                "MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"
            ],
        )
        status = ledger.status()["google-ai-studio"]
        self.assertEqual(observed_requests, [1])
        self.assertEqual(status["requests"], 1)
        self.assertEqual(status["halt_reason"], "provider_response_invalid")

    def test_pacing_rechecks_reservation_before_catalog_egress(self) -> None:
        environment = {
            **fixture_budget_environment(self),
            "MAVERICK_CERTIFICATION_ALLOW_LIVE": "1",
            "MAVERICK_CERTIFICATION_MAX_COST_MICROUSD": "3500000",
        }
        order = []
        ledger = mock.Mock()
        ledger.reserve.side_effect = lambda **_kwargs: (
            order.append("reserve") or (4 if len(order) == 1 else 0)
        )
        ledger.halt.side_effect = lambda *_args, **_kwargs: order.append(
            "halt"
        )

        async def paced_sleep(delay):
            self.assertEqual(delay, 4)
            order.append("sleep")

        def unavailable_catalog(*_args, **_kwargs):
            order.append("catalog")
            return None

        with mock.patch.dict(
            "os.environ",
            environment,
            clear=True,
        ), mock.patch.object(
            probe,
            "CertificationBudgetLedger",
            return_value=ledger,
        ), mock.patch.object(
            probe,
            "inspect_native_runtime_artifact",
            return_value=ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
        ), mock.patch.object(
            probe.asyncio,
            "sleep",
            side_effect=paced_sleep,
        ), mock.patch.object(
            probe,
            "discover_antigravity_native_catalog",
            side_effect=unavailable_catalog,
        ):
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "native_agent_model_unavailable",
            ):
                asyncio.run(probe._probe())

        self.assertEqual(
            order,
            ["reserve", "sleep", "reserve", "catalog", "halt"],
        )


if __name__ == "__main__":
    unittest.main()
