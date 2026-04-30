"""Environment defaults for local test runs.

Tests must not depend on deployment secrets or systemd environment files. These
defaults are intentionally deterministic and suitable only for test processes.
"""

from __future__ import annotations

import os


def apply_test_environment_defaults() -> None:
    """Set test-only defaults for secrets required by core bootstrap paths."""

    os.environ.setdefault("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS", "1")
    os.environ.setdefault("MAVERICK_ADMIN_USERNAME", "admin")
    os.environ.setdefault("MAVERICK_ADMIN_PASSWORD", "maverick")
    os.environ.setdefault("MAVERICK_RUNTIME_API_SECRET", "maverick-test-runtime-api-secret")
    os.environ.setdefault("MAVERICK_SECRET_STORE_KEY", "maverick-test-secret-store-key")
