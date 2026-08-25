"""Tests for app surface descriptor secret selector resolution."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.apps.surface_descriptors import (
    AppSurfaceSecretSelector,
    app_cli_command_execution_metadata,
    app_secret_requests_for_arguments,
)


class SurfaceDescriptorSecretSelectorTest(unittest.TestCase):
    def test_cli_command_timeout_is_bounded_and_command_specific(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cli").mkdir()
            descriptor = root / "cli/command_schemas.json"
            descriptor.write_text(
                json.dumps({"commands": {"dev": {"timeout_seconds": 600}}}),
                encoding="utf-8",
            )
            self.assertEqual(app_cli_command_execution_metadata(root, "dev").timeout_seconds, 600)

            descriptor.write_text(
                json.dumps({"commands": {"dev": {"timeout_seconds": 901}}}),
                encoding="utf-8",
            )
            self.assertIsNone(app_cli_command_execution_metadata(root, "dev").timeout_seconds)

    def test_lookup_does_not_scope_non_resource_selector(self) -> None:
        selector = AppSurfaceSecretSelector(
            logical_names=["gmail-oauth-client-id", "gmail-oauth-client-secret"],
            resource_lookup={"kind": "mail_connection_from_arguments"},
        )

        requests = app_secret_requests_for_arguments(
            [selector],
            {"thread_id": "email_thread_1"},
            resource_lookup=lambda _selector: {
                "requires_secrets": True,
                "resource_type": "mail_connection",
                "resource_id": "mail_connection_1",
            },
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].logical_names, ["gmail-oauth-client-id", "gmail-oauth-client-secret"])
        self.assertIsNone(requests[0].resource_type)
        self.assertIsNone(requests[0].resource_id)

    def test_lookup_supplies_id_for_explicit_resource_selector(self) -> None:
        selector = AppSurfaceSecretSelector(
            logical_names=["gmail-refresh-token"],
            resource_type="mail_connection",
            resource_lookup={"kind": "mail_connection_from_arguments"},
        )

        requests = app_secret_requests_for_arguments(
            [selector],
            {"thread_id": "email_thread_1"},
            resource_lookup=lambda _selector: {
                "requires_secrets": True,
                "resource_type": "mail_connection",
                "resource_id": "mail_connection_1",
            },
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].logical_names, ["gmail-refresh-token"])
        self.assertEqual(requests[0].resource_type, "mail_connection")
        self.assertEqual(requests[0].resource_id, "mail_connection_1")


if __name__ == "__main__":
    unittest.main()
