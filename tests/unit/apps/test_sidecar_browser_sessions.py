"""Tests for hashed sidecar browser bootstrap and session authority."""

from __future__ import annotations

import unittest

from core.apps.sidecar_browser_sessions import (
    SidecarBrowserBinding,
    SidecarBrowserSessionStore,
)


class SidecarBrowserSessionStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1000.0
        self.store = SidecarBrowserSessionStore(clock=lambda: self.now)
        self.binding = SidecarBrowserBinding(
            actor_user_id="user-a",
            workspace_id="workspace-a",
            app_id="demo",
            sidecar_id="web",
            host="sc-a.sidecars.localhost:8000",
            origin="http://sc-a.sidecars.localhost:8000",
            platform_origin="http://localhost:8000",
            generation_id="generation-a",
            sidecar_instance_id="instance-a",
            clean_path="/index.html",
            secure=False,
            content_security_policy="default-src 'self'; frame-ancestors http://localhost:8000",
        )

    def test_ticket_is_hashed_one_shot_host_bound_and_expires(self) -> None:
        issued = self.store.issue_ticket(self.binding)

        self.assertNotIn(issued.value, repr(self.store._tickets))
        self.assertNotIn(issued.confirmation_value, repr(self.store._confirmations))
        wrong_host = self.store.consume_ticket(issued.value, host="sc-b.sidecars.localhost:8000")
        replay = self.store.consume_ticket(issued.value, host=self.binding.host)

        self.assertIsNone(wrong_host)
        self.assertIsNone(replay)

        expired = self.store.issue_ticket(self.binding, ttl_seconds=1)
        self.now += 2
        self.assertIsNone(self.store.consume_ticket(expired.value, host=self.binding.host))

    def test_bootstrap_confirmation_is_actor_bound_and_changes_only_after_validated_bootstrap(self) -> None:
        ticket = self.store.issue_ticket(self.binding)

        self.assertEqual(
            self.store.bootstrap_confirmation_status(
                ticket.confirmation_value,
                actor_user_id="user-a",
                workspace_id="workspace-a",
                app_id="demo",
                sidecar_id="web",
                sidecar_instance_id="instance-a",
            ),
            "pending",
        )
        self.assertIsNone(
            self.store.bootstrap_confirmation_status(
                ticket.confirmation_value,
                actor_user_id="user-b",
                workspace_id="workspace-a",
                app_id="demo",
                sidecar_id="web",
                sidecar_instance_id="instance-a",
            )
        )

        issued = self.store.consume_ticket(ticket.value, host=self.binding.host)
        assert issued is not None
        self.assertEqual(
            self.store.bootstrap_confirmation_status(
                ticket.confirmation_value,
                actor_user_id="user-a",
                workspace_id="workspace-a",
                app_id="demo",
                sidecar_id="web",
                sidecar_instance_id="instance-a",
            ),
            "pending",
        )
        self.assertTrue(self.store.confirm_bootstrap(issued.session))
        self.assertEqual(
            self.store.bootstrap_confirmation_status(
                ticket.confirmation_value,
                actor_user_id="user-a",
                workspace_id="workspace-a",
                app_id="demo",
                sidecar_id="web",
                sidecar_instance_id="instance-a",
            ),
            "ready",
        )

    def test_live_session_touches_rotates_without_parallel_request_breakage_and_revokes(self) -> None:
        ticket = self.store.issue_ticket(self.binding)
        issued = self.store.consume_ticket(ticket.value, host=self.binding.host)
        assert issued is not None
        self.assertNotIn(issued.value, repr(self.store._sessions))

        first = self.store.validate_and_touch(issued.value, host=self.binding.host)
        self.assertIsNotNone(first)
        self.assertIsNone(first.rotated_value)

        self.now += 61
        rotated = self.store.validate_and_touch(issued.value, host=self.binding.host)
        assert rotated is not None and rotated.rotated_value is not None
        concurrent_old = self.store.validate_and_touch(issued.value, host=self.binding.host)
        current = self.store.validate_and_touch(rotated.rotated_value, host=self.binding.host)
        self.assertIsNotNone(concurrent_old)
        self.assertIsNotNone(current)

        self.store.revoke_app(workspace_id="workspace-a", app_id="demo")
        self.assertIsNone(self.store.validate_and_touch(rotated.rotated_value, host=self.binding.host))

    def test_dual_cookie_session_can_touch_without_rotating(self) -> None:
        ticket = self.store.issue_ticket(self.binding)
        issued = self.store.consume_ticket(ticket.value, host=self.binding.host)
        assert issued is not None

        self.now += 61
        validated = self.store.validate_and_touch(
            issued.value,
            host=self.binding.host,
            rotate=False,
        )

        self.assertIsNotNone(validated)
        assert validated is not None
        self.assertIsNone(validated.rotated_value)
        self.assertIsNotNone(self.store.validate(issued.value, host=self.binding.host))

    def test_idle_and_absolute_expiry_fail_closed(self) -> None:
        ticket = self.store.issue_ticket(self.binding)
        issued = self.store.consume_ticket(ticket.value, host=self.binding.host)
        assert issued is not None

        self.now += 301
        self.assertIsNone(self.store.validate_and_touch(issued.value, host=self.binding.host))

        ticket = self.store.issue_ticket(self.binding)
        issued = self.store.consume_ticket(ticket.value, host=self.binding.host)
        assert issued is not None
        current_value = issued.value
        for _index in range(11):
            self.now += 299
            validated = self.store.validate_and_touch(current_value, host=self.binding.host)
            self.assertIsNotNone(validated)
            assert validated is not None
            current_value = validated.rotated_value or current_value
        self.now = issued.session.absolute_expires_at + 1
        self.assertIsNone(self.store.validate_and_touch(current_value, host=self.binding.host))


if __name__ == "__main__":
    unittest.main()
