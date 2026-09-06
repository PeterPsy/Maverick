"""Probe credentials/ambient environment alone never authorize paid requests."""

import asyncio
import json
import unittest

from core.providers.certification_probe_budget import CertificationProbeTransport
from core.providers.errors import CapabilityCertificateError
from core.providers.google_interactions_models import GOOGLE_INTERACTIONS_ENDPOINT


class Transport:
    endpoint = GOOGLE_INTERACTIONS_ENDPOINT

    def __init__(self):
        self.calls = 0
        self.closed = False

    async def stream(self, **kwargs):
        self.calls += 1
        try:
            yield {"synthetic": True}
        finally:
            self.closed = True


class CertificationProbeBudgetTest(unittest.TestCase):
    def make(self, *, maximum="1000000"):
        return CertificationProbeTransport(Transport(), provider_id="google-ai-studio", environment={
            "MAVERICK_CERTIFICATION_ALLOW_LIVE": "1", "MAVERICK_CERTIFICATION_MAX_COST_MICROUSD": maximum,
        })

    def payload(self):
        return {"model": "gemini-3.6-flash", "input": "synthetic",
                "generation_config": {"max_output_tokens": 2_048}}

    def run_request(self, budget, payload=None):
        async def run():
            return [item async for item in budget.stream(payload=payload or self.payload(), credential=None)]
        return asyncio.run(run())

    def test_explicit_bounded_operator_opt_in_is_required(self):
        for env in ({}, {"MAVERICK_CERTIFICATION_ALLOW_LIVE": "1"},
                    {"MAVERICK_CERTIFICATION_MAX_COST_MICROUSD": "10000"}):
            with self.assertRaisesRegex(CapabilityCertificateError, "opt_in_required"):
                CertificationProbeTransport(Transport(), provider_id="google-ai-studio", environment=env)
        for value in ("0", "-1", "NaN", "100000001"):
            with self.assertRaises(CapabilityCertificateError):
                self.make(maximum=value)

    def test_budget_fences_before_egress_and_does_not_refund(self):
        budget = self.make(maximum="1")
        with self.assertRaisesRegex(CapabilityCertificateError, "budget_exceeded"):
            self.run_request(budget)
        self.assertEqual(budget.transport.calls, 0)
        budget = self.make()
        for _ in range(3):
            self.run_request(budget)
        self.assertGreater(budget.reserved, 0)
        before = budget.reserved
        with self.assertRaisesRegex(CapabilityCertificateError, "request_limit"):
            self.run_request(budget)
        self.assertEqual(budget.reserved, before)
        self.assertTrue(budget.transport.closed)

    def test_wire_identity_and_input_output_bounds_are_checked(self):
        for patch in ({"model": "other"}, {"input": "x" * 262_144},
                      {"generation_config": {"max_output_tokens": True}},
                      {"generation_config": {"max_output_tokens": 65_536}}):
            budget = self.make()
            with self.assertRaises(CapabilityCertificateError):
                self.run_request(budget, {**self.payload(), **patch})
            self.assertEqual(budget.transport.calls, 0)

    def test_stateful_requests_reserve_retained_history_not_only_wire_bytes(self):
        budget = self.make()
        self.run_request(budget)
        previous = budget.retained_context_ceiling
        reserved = budget.reserved
        payload = {**self.payload(), "previous_interaction_id": "synthetic-interaction"}
        wire_ceiling = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 64

        self.run_request(budget, payload)

        self.assertEqual(budget.reserved - reserved, budget.pricing.usage_cost_microusd(
            wire_ceiling + previous, 2_048,
        ))
        self.assertEqual(budget.retained_context_ceiling, wire_ceiling + previous + 2_048)

    def test_retained_history_is_bounded_before_a_stateful_request(self):
        budget = self.make()
        budget.retained_context_ceiling = budget.profile.policy_ceiling.max_input_tokens
        with self.assertRaisesRegex(CapabilityCertificateError, "request_limit"):
            self.run_request(budget, {**self.payload(), "previous_interaction_id": "synthetic"})
        self.assertEqual(budget.transport.calls, 0)
        self.assertEqual(budget.reserved, 0)


if __name__ == "__main__":
    unittest.main()
