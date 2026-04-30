"""Helpers for keeping expensive integration tests out of the fast loop."""

from __future__ import annotations

import os
import unittest


INTEGRATION_LEVELS = {"integration", "slow", "all", "pre-merge", "pre_merge", "full"}
FULL_LEVELS = {"e2e", "full", "all"}
SLOW_LEVELS = INTEGRATION_LEVELS | FULL_LEVELS


def slow_tests_enabled() -> bool:
    """Return whether explicitly slow tests should run in this process."""

    if os.environ.get("MAVERICK_TEST_FULL_ONLY") == "1":
        return False
    return os.environ.get("MAVERICK_TEST_LEVEL", "fast").strip().lower() in SLOW_LEVELS


def slow_test_class(reason: str):
    """Class decorator that skips slow test classes outside slow/all runs."""

    return unittest.skipUnless(slow_tests_enabled(), reason)


def integration_tests_enabled() -> bool:
    """Return whether integration tests should run in this process."""

    if os.environ.get("MAVERICK_TEST_FULL_ONLY") == "1":
        return False
    return os.environ.get("MAVERICK_TEST_LEVEL", "fast").strip().lower() in INTEGRATION_LEVELS


def full_tests_enabled() -> bool:
    """Return whether full end-to-end tests should run in this process."""

    return os.environ.get("MAVERICK_TEST_LEVEL", "fast").strip().lower() in FULL_LEVELS


def integration_test(reason: str):
    """Function/class decorator for tests that need platform integration wiring."""

    return unittest.skipUnless(integration_tests_enabled(), reason)


def full_test(reason: str):
    """Function/class decorator for full end-to-end tests with heavyweight dependencies."""

    return unittest.skipUnless(full_tests_enabled(), reason)
