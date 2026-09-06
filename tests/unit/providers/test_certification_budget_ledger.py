"""Cross-process certification spend/quota reservations precede any egress."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from core.providers.certification_budget_ledger import (
    CertificationBudgetLedger, CertificationBudgetLimit,
)
from core.providers.errors import CapabilityCertificateError


class CertificationBudgetLedgerTest(unittest.TestCase):
    def test_policy_cannot_exceed_p6_five_dollar_authorization_or_upgrade_google(self):
        for limit in (
            CertificationBudgetLimit("openrouter", "paid", 5_000_001, 200, 0),
            CertificationBudgetLimit("google-ai-studio", "paid", 1, 80, 15),
            CertificationBudgetLimit("google-ai-studio", "free_tier", 1, 80, 15),
        ):
            with self.subTest(limit=limit), self.assertRaisesRegex(CapabilityCertificateError, "policy_invalid"):
                limit.validate()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "budget.sqlite3"
        self.limits = (
            CertificationBudgetLimit("openrouter", "paid", 4_500_000, 200, 0),
            CertificationBudgetLimit("google-ai-studio", "free_tier", 0, 80, 15),
        )
        self.ledger = CertificationBudgetLedger.create(
            self.path, limits=self.limits, authorization_ref="a" * 64,
        )

    def reserve(self, ledger=None, *, provider="openrouter", cost=1_000_000, now=100):
        return (ledger or self.ledger).reserve(
            provider_id=provider, cost_microusd=cost,
            payload_digest="b" * 64, run_id="test-run", now=now,
        )

    def test_restart_never_resets_or_refunds_reservations(self):
        self.reserve()
        reopened = CertificationBudgetLedger(self.path, policy_digest=self.ledger.policy_digest)
        self.reserve(reopened, cost=3_000_000)
        with self.assertRaisesRegex(CapabilityCertificateError, "budget_exceeded"):
            self.reserve(reopened)
        self.assertEqual(reopened.status()["openrouter"]["reserved_microusd"], 4_000_000)
        self.assertEqual(reopened.status()["openrouter"]["requests"], 2)
        with self.assertRaises(FileExistsError):
            CertificationBudgetLedger.create(self.path, limits=self.limits, authorization_ref="a" * 64)

    def test_concurrent_workers_share_one_atomic_ceiling(self):
        def attempt(_):
            ledger = CertificationBudgetLedger(self.path, policy_digest=self.ledger.policy_digest)
            try:
                self.reserve(ledger)
                return True
            except CapabilityCertificateError as error:
                self.assertEqual(str(error), "certification_budget_exceeded")
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(12))), 4)
        self.assertEqual(self.ledger.status()["openrouter"]["requests"], 4)

    def test_process_death_after_reservation_cannot_restore_credit(self):
        code = """
import os, sys
from pathlib import Path
from core.providers.certification_budget_ledger import CertificationBudgetLedger
ledger = CertificationBudgetLedger(Path(sys.argv[1]), policy_digest=sys.argv[2])
ledger.reserve(provider_id='openrouter', cost_microusd=4_000_000,
               payload_digest='b' * 64, run_id='crash-before-transport')
os._exit(19)
"""
        child = subprocess.run([sys.executable, "-c", code, str(self.path), self.ledger.policy_digest],
                               capture_output=True, timeout=10, check=False)
        self.assertEqual(child.returncode, 19, child.stderr.decode())
        self.assertEqual(self.ledger.status()["openrouter"]["reserved_microusd"], 4_000_000)
        with self.assertRaisesRegex(CapabilityCertificateError, "budget_exceeded"):
            self.reserve()

    def test_free_tier_has_finite_quota_and_pacing_not_paid_credit(self):
        self.reserve(provider="google-ai-studio", cost=300_000)
        delay = self.reserve(provider="google-ai-studio", cost=300_000, now=101)
        self.assertEqual(delay, 14)
        self.assertEqual(self.ledger.status()["google-ai-studio"]["requests"], 1)
        for ordinal in range(1, 80):
            self.reserve(provider="google-ai-studio", cost=300_000, now=100 + 15 * ordinal)
        with self.assertRaisesRegex(CapabilityCertificateError, "quota_exceeded"):
            self.reserve(provider="google-ai-studio", now=10_000)
        status = self.ledger.status()["google-ai-studio"]
        self.assertEqual(status["reserved_microusd"], 0)
        self.assertEqual(status["list_price_reserved_microusd"], 24_000_000)

    def test_halt_is_durable_and_cannot_be_cleared_by_a_new_transport(self):
        self.ledger.halt("openrouter", reason="provider_quota_exceeded")
        reopened = CertificationBudgetLedger(self.path, policy_digest=self.ledger.policy_digest)
        with self.assertRaisesRegex(CapabilityCertificateError, "budget_halted"):
            self.reserve(reopened)
        self.assertEqual(reopened.status()["openrouter"]["requests"], 0)

    def test_policy_mismatch_missing_corrupt_or_shared_ledger_fail_closed(self):
        with self.assertRaisesRegex(CapabilityCertificateError, "ledger_invalid"):
            CertificationBudgetLedger(self.path, policy_digest="c" * 64)
        with self.assertRaisesRegex(CapabilityCertificateError, "ledger_invalid"):
            CertificationBudgetLedger(self.path.with_name("absent"), policy_digest=self.ledger.policy_digest)
        link = self.path.with_name("alias")
        link.symlink_to(self.path)
        with self.assertRaisesRegex(CapabilityCertificateError, "ledger_invalid"):
            CertificationBudgetLedger(link, policy_digest=self.ledger.policy_digest)
        self.path.chmod(0o644)
        with self.assertRaisesRegex(CapabilityCertificateError, "ledger_invalid"):
            self.reserve()
        self.path.chmod(0o600)
        self.path.write_bytes(b"not a ledger")
        with self.assertRaisesRegex(CapabilityCertificateError, "ledger_invalid"):
            self.reserve()

    def test_invalid_values_or_unconfigured_provider_cannot_reserve(self):
        for value in (True, -1, 0, 1.5):
            with self.assertRaises(CapabilityCertificateError):
                self.reserve(cost=value)
        with self.assertRaises(CapabilityCertificateError):
            self.reserve(provider="other")
        self.assertEqual(self.ledger.status()["openrouter"]["requests"], 0)


if __name__ == "__main__":
    unittest.main()
