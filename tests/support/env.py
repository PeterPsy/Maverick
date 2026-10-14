"""Environment defaults for local test runs.

Tests must not depend on deployment secrets or systemd environment files. These
defaults are intentionally deterministic and suitable only for test processes.
"""

from __future__ import annotations

import os


def apply_test_environment_defaults() -> None:
    """Set test-only defaults for secrets required by core bootstrap paths."""

    os.environ.setdefault("LOOPINO_ALLOW_INSECURE_TEST_DEFAULTS", "1")
    os.environ.setdefault("LOOPINO_ADMIN_USERNAME", "admin")
    os.environ.setdefault("LOOPINO_ADMIN_PASSWORD", "loopino")
    os.environ.setdefault("LOOPINO_RUNTIME_API_SECRET", "loopino-test-runtime-api-secret")
    os.environ.setdefault("LOOPINO_SECRET_STORE_KEY", "loopino-test-secret-store-key")
