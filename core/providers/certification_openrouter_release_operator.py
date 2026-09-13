"""Operator CLI for the production OpenRouter certification release."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.api.platform_state import bootstrap_platform_state
from core.providers.certification_natural_artifacts import write_new_json
from core.providers.certification_natural_credential import (
    production_control_environment,
)
from core.providers.certification_openrouter_release import (
    activate_certified_openrouter_release,
)
from core.providers.certification_pipeline import load_ed25519_private_key
from core.providers.certification_records import signed_run_from_json


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def activate_openrouter_release_cli(argv: list[str] | None = None) -> int:
    """Verify, publish, and bind one signed release as a non-default profile."""
    parser = argparse.ArgumentParser(
        prog="run_agentic_certification.py activate-openrouter"
    )
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--signed-run", type=Path, required=True)
    parser.add_argument("--signer-key-id", required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirmation",
        required=True,
        choices=("activate-certified-openrouter-non-default",),
    )
    args = parser.parse_args(argv)
    control_root = _external_path(parser, args.control_root, "control root")
    signed_run_path = _external_path(parser, args.signed_run, "signed run")
    private_key_path = _external_path(parser, args.private_key_file, "private key")
    output_path = args.output.resolve()
    if output_path.exists() or output_path.is_relative_to(REPOSITORY_ROOT):
        parser.error("output must be a new file outside the source checkout")
    if private_key_path.stat().st_mode & 0o077:
        parser.error("--private-key-file must not be group/world accessible")
    signed_run = signed_run_from_json(_read_bounded(signed_run_path))
    if signed_run.signer_key_id != args.signer_key_id:
        parser.error("--signer-key-id does not match the signed run")
    private_key = load_ed25519_private_key(private_key_path)
    with production_control_environment(control_root):
        state = bootstrap_platform_state(
            start_path=control_root,
            install_builtin_apps=True,
            bootstrap_admin=False,
        )
        result = activate_certified_openrouter_release(
            state,
            signed_run=signed_run,
            trusted_keys={args.signer_key_id: private_key.public_key()},
        )
    write_new_json(output_path, result)
    print(output_path, flush=True)
    return 0


def _external_path(
    parser: argparse.ArgumentParser,
    path: Path,
    label: str,
) -> Path:
    resolved = path.resolve(strict=True)
    if resolved.is_relative_to(REPOSITORY_ROOT):
        parser.error(f"{label} must be outside the source checkout")
    return resolved


def _read_bounded(path: Path) -> str:
    with path.open("rb") as source:
        payload = source.read(262_145)
    if len(payload) > 262_144:
        raise ValueError("certification_artifact_too_large")
    return payload.decode("utf-8")


__all__ = ["activate_openrouter_release_cli"]
