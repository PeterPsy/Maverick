#!/usr/bin/env python3
"""Run and sign an agentic certification suite; never emit evidence on failure."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.providers.certification_pipeline import (
    execute_certification_suite,
    load_ed25519_private_key,
    sign_certification_run,
    signed_run_to_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--suite-version", required=True)
    parser.add_argument("--adapter-artifact-digest", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--matrix-revision", required=True)
    parser.add_argument("--artifact", action="append", type=Path, required=True)
    parser.add_argument("--evidence-ref", action="append", required=True)
    parser.add_argument("--signer-key-id", required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    root = REPOSITORY_ROOT
    run = execute_certification_suite(
        command=command,
        cwd=root,
        suite_id=args.suite_id,
        suite_version=args.suite_version,
        adapter_artifact_digest=args.adapter_artifact_digest,
        artifact_paths=tuple(root / item for item in args.artifact),
        matrix_path=root / args.matrix,
        matrix_revision=args.matrix_revision,
        evidence_refs=tuple(args.evidence_ref),
    )
    signed = sign_certification_run(
        run,
        signer_key_id=args.signer_key_id,
        private_key=load_ed25519_private_key(args.private_key_file),
    )
    with args.output.open("x", encoding="utf-8") as output:
        output.write(signed_run_to_json(signed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
