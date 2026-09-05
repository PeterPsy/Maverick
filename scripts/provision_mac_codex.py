#!/usr/bin/env python3
"""Explicit operator-only offline encryption; never outputs credentials."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.local_runtime.provisioning import MAX_BYTES, seal_auth, write_private_new


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--auth-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--expected-fingerprint", required=True)
    parser.add_argument("--confirm-account-access-transfer", action="store_true", required=True)
    args = parser.parse_args()
    try:
        with args.request.open("rb") as source:
            request = source.read(4097)
        with args.auth_file.open("rb") as source:
            auth = source.read(MAX_BYTES + 1)
        envelope = seal_auth(request, auth, origin=args.origin, workspace=args.workspace, fingerprint=args.expected_fingerprint)
        write_private_new(args.output, envelope)
    except Exception:
        # Driver/JSON errors can contain sensitive input. Never render them.
        print("Provisioning failed. Check scope, fingerprint, expiry, auth format and output path.", file=sys.stderr)
        return 1
    print("Encrypted device envelope created. Deliver privately; never commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
