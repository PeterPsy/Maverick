"""Background grants stay bounded to a client, app origin and action list."""

from dataclasses import replace
import unittest

from core.apps.app_background_grants import ABSOLUTE_SECONDS, IDLE_SECONDS, AppBackgroundGrantStore
from core.apps.sidecar_browser_sessions import SidecarBrowserBinding


class BackgroundGrantTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.store = AppBackgroundGrantStore(clock=lambda: self.now)
        self.binding = SidecarBrowserBinding("actor", "workspace", "demo", "frame", "af-demo.test", "https://af-demo.test", "https://maverick.test", "generation", "login", "/apps/demo/", True, "", platform_session_id="login")
        self.origin = "chrome-extension://" + "a" * 32

    def test_only_exact_extension_and_host_can_use_a_grant(self):
        token = self.store.issue(self.binding, self.origin, ["read"])
        grant = self.store.validate(token, host=self.binding.host, client_origin=self.origin)
        self.assertEqual(grant.actions, {"read"})
        self.assertEqual(grant.binding, self.binding)
        self.assertIsNone(self.store.validate(token, host="other.test", client_origin=self.origin))
        self.assertIsNone(self.store.validate(token, host=self.binding.host, client_origin="chrome-extension://" + "b" * 32))
        self.store.revoke(token)
        self.assertIsNone(self.store.validate(token, host=self.binding.host, client_origin=self.origin))

    def test_idle_renewal_cannot_outlive_the_absolute_limit(self):
        token = self.store.issue(self.binding, self.origin, ["read"])
        for _ in range(ABSOLUTE_SECONDS // (IDLE_SECONDS - 1) + 1):
            self.now += IDLE_SECONDS - 1
            grant = self.store.validate(token, host=self.binding.host, client_origin=self.origin)
            if self.now >= 100 + ABSOLUTE_SECONDS:
                self.assertIsNone(grant)
            else:
                self.assertIsNotNone(grant)
                self.store.touch(token)

    def test_expired_grant_and_invalid_scope_fail_closed(self):
        token = self.store.issue(self.binding, self.origin, ["read"])
        self.now += IDLE_SECONDS
        self.assertIsNone(self.store.validate(token, host=self.binding.host, client_origin=self.origin))
        for origin, actions in [("https://website.test", ["read"]), (self.origin, []), (self.origin, ["read", "read"]), (self.origin, ["../other"]), (self.origin, [None])]:
            with self.assertRaises(ValueError):
                self.store.issue(self.binding, origin, actions)

    def test_grants_are_bounded_per_app_principal(self):
        for _ in range(16):
            self.store.issue(self.binding, self.origin, ["read"])
        with self.assertRaisesRegex(ValueError, "limit"):
            self.store.issue(self.binding, self.origin, ["read"])
        with self.assertRaisesRegex(ValueError, "limit"):
            self.store.issue(replace(self.binding, clean_path="/apps/demo/other"), self.origin, ["read"])
        self.store.issue(replace(self.binding, actor_user_id="other"), self.origin, ["read"])
