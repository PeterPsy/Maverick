"""Unit tests for invocation-scoped app-to-sidecar capabilities."""

from __future__ import annotations

import unittest

from core.apps.models import HttpSidecarRouteRule
from core.apps.sidecar_entrypoint_capabilities import (
    SidecarEntrypointCapabilityBinding,
    SidecarEntrypointCapabilityError,
    SidecarEntrypointCapabilityStore,
)


class SidecarEntrypointCapabilityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.store = SidecarEntrypointCapabilityStore(now=lambda: self.now)
        self.binding = SidecarEntrypointCapabilityBinding(
            invocation_id="invoke-1",
            workspace_id="workspace-a",
            app_id="design-studio",
            service_id="opendesign",
            surface="reference",
            actor_user_id="user-1",
            runtime_session_id="runtime-1",
            routes=[
                HttpSidecarRouteRule(method="GET", path_template="/api/projects/{id}", static_tree=False)
            ],
            ttl_seconds=30,
            request_budget=2,
            max_request_body_bytes=0,
            max_response_body_bytes=4096,
        )

    def test_authorize_consumes_budget_and_matches_exact_route(self) -> None:
        issued = self.store.issue(self.binding)

        first = self.store.authorize(
            issued.value,
            method="GET",
            path="/api/projects/od_1",
            request_body_bytes=0,
        )
        second = self.store.authorize(
            issued.value,
            method="HEAD",
            path="/api/projects/od_2",
            request_body_bytes=0,
        )

        self.assertEqual(first.binding.invocation_id, "invoke-1")
        self.assertEqual(first.remaining_requests, 1)
        self.assertEqual(second.remaining_requests, 0)
        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "request_budget_exhausted"):
            self.store.authorize(
                issued.value,
                method="GET",
                path="/api/projects/od_3",
                request_body_bytes=0,
            )

    def test_reference_route_cannot_escalate_or_change_scope(self) -> None:
        issued = self.store.issue(self.binding)

        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "route_not_allowed"):
            self.store.authorize(
                issued.value,
                method="POST",
                path="/api/projects/od_1",
                request_body_bytes=0,
            )
        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "scope_mismatch"):
            self.store.authorize(
                issued.value,
                method="GET",
                path="/api/projects/od_1",
                request_body_bytes=0,
                workspace_id="workspace-b",
            )
        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "scope_mismatch"):
            self.store.authorize(
                issued.value,
                method="GET",
                path="/api/projects/od_1",
                request_body_bytes=0,
                service_id="other-service",
            )

    def test_expiry_revocation_and_body_limit_fail_closed(self) -> None:
        issued = self.store.issue(self.binding)
        self.now = 131.0
        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "capability_expired"):
            self.store.authorize(
                issued.value,
                method="GET",
                path="/api/projects/od_1",
                request_body_bytes=0,
            )

        issued = self.store.issue(self.binding)
        self.store.revoke_invocation("invoke-1")
        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "capability_revoked"):
            self.store.authorize(
                issued.value,
                method="GET",
                path="/api/projects/od_1",
                request_body_bytes=0,
            )

        writable = SidecarEntrypointCapabilityBinding(
            **{
                **self.binding.__dict__,
                "invocation_id": "invoke-2",
                "surface": "cli",
                "routes": [
                    HttpSidecarRouteRule(method="POST", path_template="/api/projects", static_tree=False)
                ],
                "max_request_body_bytes": 3,
            }
        )
        issued = self.store.issue(writable)
        with self.assertRaisesRegex(SidecarEntrypointCapabilityError, "request_body_too_large"):
            self.store.authorize(
                issued.value,
                method="POST",
                path="/api/projects",
                request_body_bytes=4,
            )

    def test_store_keeps_only_capability_hashes(self) -> None:
        issued = self.store.issue(self.binding)

        self.assertNotIn(issued.value, repr(self.store))
        self.assertFalse(self.store.contains_raw_value(issued.value))


if __name__ == "__main__":
    unittest.main()
