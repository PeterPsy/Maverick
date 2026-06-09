"""Tests for Maverick's Node.js runtime policy."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.shared.node_runtime import (
    MINIMUM_NODE_VERSION_TEXT,
    NodeVersion,
    node_runtime_diagnostic,
    node_version_supported,
    parse_node_version,
)


class NodeRuntimePolicyTestCase(unittest.TestCase):
    def test_parse_node_version_accepts_cli_output(self) -> None:
        self.assertEqual(parse_node_version("v24.14.0\n"), NodeVersion(24, 14, 0))
        self.assertEqual(parse_node_version("node version 24.11.0"), NodeVersion(24, 11, 0))

    def test_node_version_policy_requires_node_24_lts(self) -> None:
        self.assertFalse(node_version_supported(NodeVersion(24, 10, 0)))
        self.assertTrue(node_version_supported(NodeVersion(24, 11, 0)))
        self.assertFalse(node_version_supported(NodeVersion(25, 0, 0)))

    def test_node_runtime_diagnostic_reports_old_node(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": "v20.18.1\n", "stderr": ""})()

        with patch("core.shared.node_runtime.shutil.which", return_value="/usr/bin/node"), patch(
            "core.shared.node_runtime.subprocess.run",
            return_value=completed,
        ):
            diagnostic = node_runtime_diagnostic()

        self.assertIsNotNone(diagnostic)
        self.assertIn("20.18.1", diagnostic or "")
        self.assertIn(MINIMUM_NODE_VERSION_TEXT, diagnostic or "")

    def test_node_runtime_diagnostic_reports_newer_major_as_outside_supported_range(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": "v26.0.0\n", "stderr": ""})()

        with patch("core.shared.node_runtime.shutil.which", return_value="/usr/bin/node"), patch(
            "core.shared.node_runtime.subprocess.run",
            return_value=completed,
        ):
            diagnostic = node_runtime_diagnostic()

        self.assertIsNotNone(diagnostic)
        self.assertIn("26.0.0", diagnostic or "")
        self.assertIn("outside the supported range", diagnostic or "")
        self.assertNotIn("too old", diagnostic or "")


if __name__ == "__main__":
    unittest.main()
