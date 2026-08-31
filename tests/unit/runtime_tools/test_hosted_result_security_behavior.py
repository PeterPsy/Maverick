from __future__ import annotations

import unittest

from core.runtime.hosted_result_security_behavior import (
    HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
    inspect_hosted_result_security_behavior,
)


class HostedResultSecurityBehaviorTest(unittest.TestCase):
    def test_all_negative_security_probes_execute(self) -> None:
        inspect_hosted_result_security_behavior.cache_clear()

        self.assertEqual(
            inspect_hosted_result_security_behavior(),
            HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
        )


if __name__ == "__main__":
    unittest.main()
