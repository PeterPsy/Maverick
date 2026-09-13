"""Operator-only entrypoint for reproducible OpenRouter natural conformance."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_behavior import BEHAVIORAL_SCENARIOS
from core.providers.certification_natural_artifacts import (
    OpenRouterNaturalOperatorConfig,
)
from core.providers.certification_natural_environment import (
    PROFILE,
    bootstrap,
    build_permit,
    configure_environment,
)
from core.providers.certification_natural_credential import (
    production_openrouter_credential,
)
from core.providers.certification_natural_execution import (
    run_openrouter_natural_scenario,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def run_openrouter_natural_cli(argv: list[str] | None = None) -> int:
    """Run one isolated scenario or a no-traffic identity preflight."""
    parser = argparse.ArgumentParser(prog="run_agentic_certification.py natural")
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--budget-ledger", type=Path, required=True)
    parser.add_argument("--budget-policy-digest", required=True)
    parser.add_argument("--signer-key-id", required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--reviewer-ref", required=True)
    parser.add_argument("--effort", choices=PROFILE[2], required=True)
    parser.add_argument("--scenario", choices=tuple(BEHAVIORAL_SCENARIOS))
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    config = _operator_config(parser, args)
    if not args.preflight and args.scenario is None:
        parser.error("--scenario is required unless --preflight is used")
    scenario = args.scenario or "preflight"
    suffix = f"openrouter-{args.effort}-{scenario}"
    run_id = f"natural-{config.source_commit[:12]}-{suffix}"
    run_root = config.job_root / f"hosted-natural-{suffix}"
    try:
        run_root.mkdir(mode=0o700)
    except FileExistsError:
        parser.error(f"run output already exists: {run_root}")
    configure_environment(run_root)
    raw_credential = production_openrouter_credential(config.control_root)
    started_at = datetime.now(tz=UTC)
    (
        state,
        actor_id,
        workspace_record,
        workspace_binding,
        credential_binding,
        definition,
        skill,
    ) = bootstrap(config, args.effort, raw_credential, run_root)
    signed, authority, adapter, ledger, adapter_version = build_permit(
        config,
        state,
        actor_id,
        workspace_record,
        workspace_binding,
        credential_binding,
        definition,
        args.effort,
        run_id,
        started_at,
        run_root,
    )
    if args.preflight:
        return _print_preflight(config, args.effort, signed, adapter, ledger)
    return run_openrouter_natural_scenario(
        config,
        scenario=scenario,
        effort=args.effort,
        state=state,
        authority=authority,
        adapter=adapter,
        signed=signed,
        ledger=ledger,
        actor_id=actor_id,
        workspace_record=workspace_record,
        workspace_binding=workspace_binding,
        credential_binding=credential_binding,
        definition=definition,
        skill=skill,
        adapter_version=adapter_version,
        started_at=started_at,
        run_root=run_root,
        suffix=suffix,
    )


def _operator_config(parser: argparse.ArgumentParser, args) -> OpenRouterNaturalOperatorConfig:
    paths = {
        "job root": args.job_root.resolve(strict=True),
        "control root": args.control_root.resolve(strict=True),
        "budget ledger": args.budget_ledger.resolve(strict=True),
        "private key": args.private_key_file.resolve(strict=True),
    }
    for label, path in paths.items():
        if path.is_relative_to(REPOSITORY_ROOT):
            parser.error(f"{label} must be outside the source checkout")
    if paths["control root"] == REPOSITORY_ROOT:
        parser.error("--control-root must identify the production checkout")
    if not paths["job root"].is_dir() or paths["job root"].is_symlink():
        parser.error("--job-root must be a real directory")
    if paths["private key"].stat().st_mode & 0o077:
        parser.error("--private-key-file must not be group/world accessible")
    reviewer_ref = str(args.reviewer_ref or "")
    if len(reviewer_ref) != 64 or any(
        character not in "0123456789abcdef" for character in reviewer_ref
    ):
        parser.error("--reviewer-ref must be a SHA-256 digest")
    signer_key_id = str(args.signer_key_id or "").strip()
    if not signer_key_id:
        parser.error("--signer-key-id is required")
    workspace = REPOSITORY_ROOT / "workspaces/default"
    if workspace.exists():
        parser.error("remove the disposable source workspaces/default before this run")
    source_commit = subprocess.check_output(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        text=True,
    ).strip()
    return OpenRouterNaturalOperatorConfig(
        repository_root=REPOSITORY_ROOT,
        job_root=paths["job root"],
        control_root=paths["control root"],
        source_commit=source_commit,
        ledger_path=paths["budget ledger"],
        ledger_policy_digest=args.budget_policy_digest,
        reviewer_ref=reviewer_ref,
        signer_key_id=signer_key_id,
        signer_key_path=paths["private key"],
    )


def _print_preflight(config, effort, signed, adapter, ledger) -> int:
    print(
        json.dumps(
            {
                "preflight": "ok",
                "provider_id": "openrouter",
                "reasoning_effort": effort,
                "source_commit": config.source_commit,
                "target_digest": signed.permit.target_digest,
                "adapter_artifact_digest": runtime_adapter_artifact_digest(adapter),
                "tcb_live_digest": signed.permit.tcb_live_digest,
                "ledger_policy_digest": ledger.policy_digest,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


__all__ = ["run_openrouter_natural_cli"]
