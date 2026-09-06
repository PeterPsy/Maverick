"""Disposable zero-network budget authority for certification unit fixtures."""

from pathlib import Path
import tempfile
from uuid import uuid4

from core.providers.certification_budget_ledger import (
    CertificationBudgetLedger, CertificationBudgetLimit,
)


def fixture_budget_environment(test_case):
    directory = tempfile.TemporaryDirectory(prefix="certification-budget-fixture-")
    test_case.addCleanup(directory.cleanup)
    path = Path(directory.name) / "budget.sqlite3"
    ledger = CertificationBudgetLedger.create(path, limits=(
        CertificationBudgetLimit("openrouter", "paid", 4_500_000, 200, 0),
        CertificationBudgetLimit("google-ai-studio", "free_tier", 0, 80, 0),
    ), authorization_ref="f" * 64)
    return {
        "MAVERICK_CERTIFICATION_BUDGET_LEDGER": str(path),
        "MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST": ledger.policy_digest,
        "MAVERICK_CERTIFICATION_RUN_NONCE": uuid4().hex,
    }
