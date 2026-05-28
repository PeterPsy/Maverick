"""Tests for app surface descriptor secret selector resolution."""

from __future__ import annotations

import unittest

from core.apps.surface_descriptors import AppSurfaceSecretSelector, app_secret_requests_for_arguments


class SurfaceDescriptorSecretSelectorTest(unittest.TestCase):
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
