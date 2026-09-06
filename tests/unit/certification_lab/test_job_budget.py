import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.certification_lab.errors import LabAuthorizationError
from core.providers.certification_budget_ledger import CertificationBudgetLedger, CertificationBudgetLimit
from core.providers.certification_job_budget import CertificationGenerationLimits, CertificationJobTransport
from core.providers.errors import CapabilityCertificateError
from core.providers.maverick_agent_provider_config import MaverickTokenCostPolicy
from tests.support.lab_permits import installed_permit


class Peer:
    endpoint = 'https://openrouter.ai/api/v1/chat/completions'

    def __init__(self):
        self.payloads = []
        self.closed = False
        self.after_first = None

    async def stream(self, *, payload, credential):
        self.payloads.append(payload)
        try:
            yield {'text': 'first'}
            if self.after_first:
                self.after_first()
            yield {'text': 'second'}
        finally:
            self.closed = True


class PermitCheck:
    def __init__(self, store, ref):
        self.store, self.ref = store, ref

    def revalidate(self, credential):
        self.store.resolve(self.ref)


class LabJobBudgetTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.permits, _key, self.permit, self.ref = installed_permit(self.root)
        self.ledger = CertificationBudgetLedger.create(self.root / 'ledger.sqlite', authorization_ref='a' * 64,
            limits=(CertificationBudgetLimit('openrouter', 'paid', 4_500_000, 10, 0),
                    CertificationBudgetLimit('google-ai-studio', 'free_tier', 0, 2, 0)))
        self.pricing = MaverickTokenCostPolicy('test-pricing', '1', 1_000_000, 1_000_000)
        self.limits = CertificationGenerationLimits('openrouter', 'model', Peer.endpoint, 100_000, 4096, self.pricing.digest)
        self.peer = Peer()

    def fence(self, **overrides):
        return CertificationJobTransport(self.peer, **{
            'ledger': self.ledger, 'run_id': 'job', 'limits': self.limits,
            'pricing': self.pricing, 'authorization': PermitCheck(self.permits, self.ref), **overrides,
        })

    def request(self, fence=None):
        async def run():
            return [item async for item in (fence or self.fence()).stream(payload={'model': 'model', 'max_tokens': 2048}, credential=None)]
        return asyncio.run(run())

    def test_all_generation_phases_and_next_turns_share_durable_budget_without_probe_round_limit(self):
        for _phase in ('exploration', 'finalization', 'recovery', 'compaction', 'next-turn', 'restart'):
            self.request()
        self.assertEqual(len(self.peer.payloads), 6)
        reopened = CertificationBudgetLedger(self.ledger.path, policy_digest=self.ledger.policy_digest)
        self.assertEqual(reopened.status()['openrouter']['requests'], 6)
        self.assertEqual(reopened.identity_digest, self.ledger.identity_digest)

    def test_missing_ledger_prices_or_endpoint_drift_denies_before_http(self):
        for changes in ({'ledger': None}, {'limits': replace(self.limits, pricing_digest='c' * 64)},
                        {'limits': replace(self.limits, endpoint='https://invalid.example')}):
            with self.subTest(changes=changes), self.assertRaises(CapabilityCertificateError):
                self.request(self.fence(**changes))
        self.assertEqual(self.peer.payloads, [])

    def test_revocation_during_pacing_is_revalidated_before_any_https(self):
        original = self.ledger.reserve
        first = True
        def paced(**kwargs):
            nonlocal first
            if first:
                first = False
                return 0.01
            return original(**kwargs)
        async def revoke(_seconds):
            self.permits.revoke(self.ref.permit_id, expected_revision=1)
        with patch.object(self.ledger, 'reserve', side_effect=paced), patch('core.providers.certification_job_budget.asyncio.sleep', side_effect=revoke):
            with self.assertRaisesRegex(LabAuthorizationError, 'revoked'):
                self.request()
        self.assertEqual(self.peer.payloads, [])
        self.assertEqual(self.ledger.status()['openrouter']['requests'], 0)

    def test_post_reservation_revalidation_does_not_refund_and_stream_revocation_closes_peer(self):
        original = self.ledger.reserve
        def revoke_after_reserve(**kwargs):
            result = original(**kwargs)
            self.permits.revoke(self.ref.permit_id, expected_revision=1)
            return result
        with patch.object(self.ledger, 'reserve', side_effect=revoke_after_reserve):
            with self.assertRaisesRegex(LabAuthorizationError, 'revoked'):
                self.request()
        self.assertEqual(self.peer.payloads, [])
        self.assertEqual(self.ledger.status()['openrouter']['requests'], 1)

    def test_revocation_during_stream_stops_delivery_and_later_generations(self):
        self.peer.after_first = lambda: self.permits.revoke(self.ref.permit_id, expected_revision=1)
        with self.assertRaisesRegex(LabAuthorizationError, 'revoked'):
            self.request()
        self.assertTrue(self.peer.closed)
        with self.assertRaises(LabAuthorizationError):
            self.request()
        self.assertEqual(len(self.peer.payloads), 1)
        self.assertEqual(self.ledger.status()['openrouter']['requests'], 1)

    def test_google_quota_is_finite_across_transport_reconstruction_never_paid(self):
        limits = replace(self.limits, provider_id='google-ai-studio')
        self.request(self.fence(limits=limits))
        self.request(self.fence(limits=limits))
        with self.assertRaisesRegex(CapabilityCertificateError, 'quota_exceeded'):
            self.request(self.fence(limits=limits))
        self.assertEqual(self.ledger.status()['google-ai-studio']['reserved_microusd'], 0)
        self.assertEqual(len(self.peer.payloads), 2)


if __name__ == '__main__':
    unittest.main()
