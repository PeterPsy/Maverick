#!/usr/bin/env python3
"""Validate the running nginx configuration and signal its verified master."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.installation.nginx_control import check_nginx, reload_nginx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Root privileges are required")
    try:
        if args.test_only:
            check_nginx()
        else:
            reload_nginx()
        print(json.dumps({"status": "validated" if args.test_only else "reloaded"}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "blocked", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
