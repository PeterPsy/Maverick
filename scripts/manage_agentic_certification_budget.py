#!/usr/bin/env python3
"""Create/inspect/stop the single operator-owned P6 spend and quota ledger."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.providers.certification_budget_ledger import (
    CertificationBudgetLedger, CertificationBudgetLimit,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    phases = parser.add_subparsers(dest="phase", required=True)
    create = phases.add_parser("create")
    create.add_argument("--authorization-ref", required=True)
    create.add_argument("--confirmation", choices=("google-project-free-tier-confirmed",), required=True)
    create.add_argument("--openrouter-max-cost-microusd", type=int, default=4_500_000)
    create.add_argument("--openrouter-max-requests", type=int, default=200)
    create.add_argument("--google-max-requests", type=int, default=80)
    create.add_argument("--google-min-interval-seconds", type=int, default=15)
    for phase in ("status", "halt"):
        action = phases.add_parser(phase)
        action.add_argument("--policy-digest", required=True)
        if phase == "halt":
            action.add_argument("--provider", choices=("google-ai-studio", "openrouter"), required=True)
    args = parser.parse_args(argv)
    if not args.ledger.is_absolute() or args.ledger.resolve().is_relative_to(ROOT.resolve()):
        parser.error("Ledger must be outside the source checkout, in a private operator directory not mounted in any tenant.")
    if args.phase == "create":
        if not 0 < args.openrouter_max_cost_microusd <= 5_000_000:
            parser.error("This P6 authorization allows at most 5 USD total on OpenRouter.")
        if args.google_min_interval_seconds < 15:
            parser.error("This P6 job requires at least 15 seconds between Google requests.")
        ledger = CertificationBudgetLedger.create(args.ledger, authorization_ref=args.authorization_ref, limits=(
            CertificationBudgetLimit("openrouter", "paid", args.openrouter_max_cost_microusd,
                                     args.openrouter_max_requests, 1),
            CertificationBudgetLimit("google-ai-studio", "free_tier", 0,
                                     args.google_max_requests, args.google_min_interval_seconds),
        ))
    else:
        ledger = CertificationBudgetLedger(args.ledger, policy_digest=args.policy_digest)
        if args.phase == "halt":
            ledger.halt(args.provider, reason="operator_stop")
    print(json.dumps({"policy_digest": ledger.policy_digest, "providers": ledger.status()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
