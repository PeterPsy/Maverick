"""Every natural-lab generation is reserved before its raw transport opens."""

import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.providers.certification_budget_ledger import (
    CertificationBudgetLedger,
    CertificationBudgetLimit,
)
from core.providers.certification_job_budget import (
    CertificationGenerationLimits,
    CertificationJobTransport,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.maverick_agent_provider_config import MaverickTokenCostPolicy


class _Peer:
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self) -> None:
        self.opened = 0
        self.closed = False

    async def stream(self, *, payload, credential):
        self.opened += 1
        try:
            yield {"text": "first"}
            yield {"text": "second"}
        finally:
            self.closed = True


class _Authorization:
    def __init__(self) -> None:
        self.calls = 0
        self.revoked = False

    def revalidate(self, credential) -> None:
        self.calls += 1
        if self.revoked:
            raise CapabilityCertificateError("certification_lab_permit_revoked")


class CertificationJobBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.ledger = CertificationBudgetLedger.create(
            self.root / "ledger.sqlite3",
            authorization_ref="a" * 64,
            limits=(
                CertificationBudgetLimit("openrouter", "paid", 4_500_000, 8, 0),
                CertificationBudgetLimit("google-ai-studio", "free_tier", 0, 2, 0),
            ),
        )
        self.pricing = MaverickTokenCostPolicy(
            "test-pricing",
            "1",
            1_000_000,
            1_000_000,
        )
        self.limits = CertificationGenerationLimits(
            "openrouter",
            "model",
            _Peer.endpoint,
            100_000,
            4_096,
            self.pricing.digest,
        )
        self.peer = _Peer()
        self.authorization = _Authorization()

    def test_all_turns_share_the_durable_ledger_without_probe_round_limit(self) -> None:
        for _ in range(6):
            self._request()
        reopened = CertificationBudgetLedger(
            self.ledger.path,
            policy_digest=self.ledger.policy_digest,
        )
        self.assertEqual(reopened.status()["openrouter"]["requests"], 6)
        self.assertEqual(self.peer.opened, 6)

    def test_post_reservation_revocation_keeps_charge_and_prevents_https(self) -> None:
        original = self.ledger.reserve

        def reserve_then_revoke(**kwargs):
            result = original(**kwargs)
            self.authorization.revoked = True
            return result

        with patch.object(self.ledger, "reserve", side_effect=reserve_then_revoke):
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_lab_permit_revoked",
            ):
                self._request()
        self.assertEqual(self.peer.opened, 0)
        self.assertEqual(self.ledger.status()["openrouter"]["requests"], 1)

    def test_wrong_endpoint_fails_before_https(self) -> None:
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certification_generation_configuration_mismatch",
        ):
            self._request(limits=replace(self.limits, endpoint="https://invalid.example"))
        self.assertEqual(self.peer.opened, 0)

    def test_google_quota_is_finite_and_never_counted_as_paid(self) -> None:
        google_limits = replace(self.limits, provider_id="google-ai-studio")
        self._request(limits=google_limits)
        self._request(limits=google_limits)
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certification_budget_quota_exceeded",
        ):
            self._request(limits=google_limits)
        status = self.ledger.status()["google-ai-studio"]
        self.assertEqual(status["requests"], 2)
        self.assertEqual(status["reserved_microusd"], 0)

    def _request(self, **overrides) -> list[dict[str, object]]:
        options = {
            "ledger": self.ledger,
            "run_id": "natural-run",
            "limits": self.limits,
            "pricing": self.pricing,
            "authorization": self.authorization,
            **overrides,
        }
        fence = CertificationJobTransport(self.peer, **options)

        async def collect():
            return [
                item
                async for item in fence.stream(
                    payload={"model": "model", "max_tokens": 2_048},
                    credential=None,
                )
            ]

        return asyncio.run(collect())


if __name__ == "__main__":
    unittest.main()
