#!/usr/bin/env python3
"""Collect conformance, then separately review/sign complete natural evidence."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.providers.certification_pipeline import (
    attach_behavioral_evidence,
    execute_certification_suite,
    load_ed25519_private_key,
    sign_certification_run,
    signed_run_to_json,
)
from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.certification_live_receipt import decode_certification_json
from core.providers.certification_records import (
    collection_from_json,
    collection_to_json,
)


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["natural"]:
        from core.providers.certification_natural_operator import (
            run_openrouter_natural_cli,
        )

        return run_openrouter_natural_cli(arguments[1:])
    if arguments[:1] == ["review-natural"]:
        from core.providers.certification_natural_review import (
            review_openrouter_natural_cli,
        )

        return review_openrouter_natural_cli(arguments[1:])
    if arguments[:1] == ["activate-openrouter"]:
        from core.providers.certification_openrouter_release_operator import (
            activate_openrouter_release_cli,
        )

        return activate_openrouter_release_cli(arguments[1:])
    parser = argparse.ArgumentParser()
    phases = parser.add_subparsers(dest="phase", required=True)
    collect = phases.add_parser("collect")
    collect.add_argument("--suite-id", required=True)
    collect.add_argument("--suite-version", required=True)
    collect.add_argument("--adapter-artifact-digest", required=True)
    collect.add_argument("--evidence-ref", action="append", required=True)
    collect.add_argument(
        "--live-probe",
        action="store_true",
        help="Explicit operator opt-in; default is fixture-only.",
    )
    collect.add_argument("--max-cost-microusd", type=int)
    collect.add_argument("--budget-ledger", type=Path)
    collect.add_argument("--budget-policy-digest")
    collect.add_argument(
        "--openrouter-control-root",
        type=Path,
        help="Resolve the production OpenRouter credential without exporting it.",
    )
    sign = phases.add_parser("sign")
    sign.add_argument("--collection-file", type=Path, required=True)
    sign.add_argument("--behavioral-evidence-file", type=Path, required=True)
    sign.add_argument("--signer-key-id", required=True)
    sign.add_argument("--private-key-file", type=Path, required=True)
    sign.add_argument(
        "--confirmation",
        required=True,
        choices=("natural-traces-reviewed",),
    )
    collect.add_argument("--output", type=Path, required=True)
    sign.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    root = REPOSITORY_ROOT
    if args.output.exists() or args.output.resolve().is_relative_to(root.resolve()):
        parser.error("Output must be a new file outside the source checkout.")
    if args.phase == "sign":
        for label, path in (
            ("collection file", args.collection_file),
            ("behavioral evidence file", args.behavioral_evidence_file),
            ("private key file", args.private_key_file),
        ):
            resolved = path.resolve(strict=True)
            if resolved.is_relative_to(root.resolve()):
                parser.error(f"The {label} must be outside the source checkout.")
        if args.private_key_file.stat().st_mode & 0o077:
            parser.error(
                "The private key file must not be group/world accessible."
            )
    if args.phase == "collect":
        if args.live_probe and (
            args.max_cost_microusd is None
            or not 0 < args.max_cost_microusd <= 100_000_000
        ):
            parser.error(
                "Live collection requires a positive bounded --max-cost-microusd."
            )
        if args.live_probe:
            if args.budget_ledger is None or not args.budget_policy_digest:
                parser.error(
                    "Live collection requires the shared --budget-ledger and "
                    "--budget-policy-digest."
                )
            if args.budget_ledger.resolve().is_relative_to(root.resolve()):
                parser.error(
                    "The operator budget ledger must not be mounted in the source "
                    "checkout."
                )
            CertificationBudgetLedger(
                args.budget_ledger,
                policy_digest=args.budget_policy_digest,
            )
        if args.openrouter_control_root is not None:
            if (
                not args.live_probe
                or args.suite_id != "maverick-openrouter-agentic-contract"
            ):
                parser.error(
                    "--openrouter-control-root is restricted to live OpenRouter "
                    "collection."
                )
            control_root = args.openrouter_control_root.resolve(strict=True)
            if control_root.is_relative_to(root.resolve()):
                parser.error(
                    "Production control root must be outside the source checkout."
                )
            from core.providers.certification_natural_credential import (
                production_openrouter_credential,
            )

            openrouter_credential = production_openrouter_credential(control_root)
        environment = dict(os.environ)
        environment["MAVERICK_CERTIFICATION_ALLOW_LIVE"] = (
            "1" if args.live_probe else "0"
        )
        environment["MAVERICK_CERTIFICATION_MAX_COST_MICROUSD"] = str(
            args.max_cost_microusd or 0
        )
        if args.live_probe:
            environment["MAVERICK_CERTIFICATION_BUDGET_LEDGER"] = str(
                args.budget_ledger
            )
            environment["MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"] = (
                args.budget_policy_digest
            )
        if args.openrouter_control_root is not None:
            environment["MAVERICK_OPENROUTER_CERTIFICATION_API_KEY"] = (
                openrouter_credential
            )
        run = execute_certification_suite(
            cwd=root,
            suite_id=args.suite_id,
            suite_version=args.suite_version,
            adapter_artifact_digest=args.adapter_artifact_digest,
            evidence_refs=tuple(args.evidence_ref),
            environment=environment,
            step_kinds=None if args.live_probe else ("fixture_contract",),
            failure_artifact_path=args.output,
        )
        serialized = collection_to_json(run)
    else:
        for label, path in (
            ("collection file", args.collection_file),
            ("behavioral evidence file", args.behavioral_evidence_file),
            ("private key file", args.private_key_file),
        ):
            if path.resolve(strict=True).is_relative_to(root.resolve()):
                parser.error(f"{label} must be outside the source checkout.")
        if args.private_key_file.stat().st_mode & 0o077:
            parser.error(
                "Private key file must not be group/world accessible."
            )
        run = collection_from_json(_read_bounded(args.collection_file))
        report = decode_certification_json(
            _read_bounded(args.behavioral_evidence_file)
        )
        run = attach_behavioral_evidence(run, report, cwd=root)
        signed = sign_certification_run(
            run,
            signer_key_id=args.signer_key_id,
            private_key=load_ed25519_private_key(args.private_key_file),
            cwd=root,
        )
        serialized = signed_run_to_json(signed)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(serialized)
    return 0


def _read_bounded(path):
    with path.open("rb") as source:
        return source.read(262_145)  # Parser rejects any byte beyond the limit.


if __name__ == "__main__":
    sys.exit(main())
