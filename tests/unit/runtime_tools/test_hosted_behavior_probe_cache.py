from __future__ import annotations

import unittest

from core.runtime.hosted_behavior_probe_cache import (
    cache_complete_behavior_probe,
)


class HostedBehaviorProbeCacheTest(unittest.TestCase):
    def test_partial_evidence_is_retried_and_only_complete_evidence_is_cached(self) -> None:
        expected = ("behavior:a", "behavior:b")
        attempts = 0

        @cache_complete_behavior_probe(expected)
        def inspect() -> tuple[str, ...]:
            nonlocal attempts
            attempts += 1
            return expected[:attempts]

        self.assertEqual(inspect(), ("behavior:a",))
        self.assertEqual(inspect(), expected)
        self.assertEqual(inspect(), expected)
        self.assertEqual(attempts, 2)

        inspect.cache_clear()
        self.assertEqual(inspect(), expected)
        self.assertEqual(attempts, 3)


if __name__ == "__main__":
    unittest.main()
