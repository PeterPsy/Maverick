#!/usr/bin/env python3
"""Rebase persisted repository-local absolute paths after moving a checkout."""

from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.shared.path_rebasing import rebase_local_state_paths


def main() -> int:
    changed_paths = rebase_local_state_paths(start_path=Path(__file__))
    for path in changed_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
