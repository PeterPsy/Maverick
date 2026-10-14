"""The shell avatar follows verified login identity, independently of service accounts."""
from dataclasses import replace
import unittest

from core.api.session_api import public_user_payload
from core.identity.errors import UserNotFoundError
from core.connected_accounts.service import complete_flow
from tests.support import connected_account_fixture as fixtures

PHOTO = "https://lh3.googleusercontent.com/a/primary=s96-c"
SECONDARY = "https://lh3.googleusercontent.com/a/secondary=s96-c"


class UserAvatarTests(unittest.TestCase):
    setUp = fixtures.ConnectedAccountFixture.setUp
    flow = fixtures.ConnectedAccountFixture.flow

    def connect(self, *, photo=PHOTO, subject="primary", mode="connect"):
        query, browser = self.flow([], mode=mode)
        return complete_flow(self.state, raw_state=query["state"][0], browser=browser,
            code="code", context=self.context, now=self.now,
            exchange=lambda *args, **kwargs: {"id_token": "signed", "scope": "profile"},
            identity_verifier=lambda *args, **kwargs: {"sub": subject, "email": subject + "@example.com", "picture": photo})[0]

    def test_secondary_connection_does_not_replace_identity_even_with_stale_context(self):
        self.connect()
        first = self.connect(mode="login")
        self.assertEqual(first.avatar_url, PHOTO)
        self.connect(photo=SECONDARY, subject="secondary")
        self.assertEqual(self.identity.get_user(self.user.user_id).avatar_url, PHOTO)
        logged_in = self.connect(photo=SECONDARY, subject="secondary", mode="login")
        self.assertEqual(logged_in.avatar_url, SECONDARY)
        self.assertEqual(logged_in.user_id, self.user.user_id)

    def test_first_service_account_does_not_supply_a_missing_identity_photo(self):
        user = self.connect(photo=SECONDARY, subject="secondary")
        self.assertIsNone(user.avatar_url)
        self.assertIsNone(self.identity.get_user(self.user.user_id).avatar_url)
        self.assertEqual(self.state.account_store.find_subject("google", "secondary").picture_url, SECONDARY)

    def test_untrusted_picture_is_not_exposed_as_identity_avatar(self):
        self.connect()
        user = self.connect(photo="https://evil.example/avatar", mode="login")
        self.assertIsNone(public_user_payload(user)["avatar_url"])

    def test_targeted_avatar_update_preserves_concurrent_roles_and_cannot_recreate_users(self):
        updated = self.identity.save_user(replace(self.user, platform_role="admin", display_name="Current name"))
        saved = self.identity.update_user_avatar(updated.user_id, PHOTO, now=self.now)
        self.assertEqual(saved.platform_role, "admin")
        self.assertEqual(saved.display_name, "Current name")
        self.identity.delete_user(updated.user_id)
        with self.assertRaises(UserNotFoundError):
            self.identity.update_user_avatar(updated.user_id, PHOTO, now=self.now)
        self.assertEqual(self.identity.list_users(), [])

    def test_legacy_user_records_need_no_migration(self):
        self.identity.collections.users.update_one({"user_id": self.user.user_id}, {"$unset": {"avatar_url": ""}})
        self.assertIsNone(self.identity.get_user(self.user.user_id).avatar_url)
        self.assertIsNone(self.connect().avatar_url)
        self.assertEqual(self.connect(mode="login").avatar_url, PHOTO)
