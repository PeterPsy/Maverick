"""Repeated bootstrap preserves membership identity and domain role constraints."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from unittest.mock import Mock

from core.workspaces.errors import WorkspaceMembershipError
from core.workspaces.service import build_workspace_membership, ensure_workspace_membership


class MembershipBootstrapTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.original = build_workspace_membership(
            membership_id="original", workspace_id="default", user_id="human", now=self.now
        )
        self.store = Mock()
        self.store.get_membership.return_value = self.original
        self.store.save_membership.side_effect = lambda record: record

    def ensure(self, **kwargs):
        return ensure_workspace_membership(
            self.store, membership_id="different-input", workspace_id="default",
            user_id="human", now=self.now + timedelta(days=1), **kwargs,
        )

    def assert_identity_preserved(self, changed):
        self.assertEqual(changed.membership_id, self.original.membership_id)
        self.assertEqual(changed.created_at, self.original.created_at)

    def test_repeated_bootstrap_does_not_recreate_existing_membership(self):
        self.assertEqual(self.ensure(), self.original)
        self.store.save_membership.assert_not_called()

    def test_role_change_preserves_id_and_creation_time(self):
        changed = self.ensure(role="admin")
        self.assert_identity_preserved(changed)
        self.assertEqual(changed.role, "admin")
        self.assertEqual(changed.updated_at, self.now + timedelta(days=1))

    def test_missing_membership_is_created(self):
        self.store.get_membership.side_effect = WorkspaceMembershipError("missing")
        created = self.ensure(role="invalid")
        self.assertEqual(created.membership_id, "different-input")
        self.assertEqual(created.status, "active")
        self.assertEqual(created.role, "member")

    def test_existing_membership_normalizes_invalid_non_admin_role(self):
        self.store.get_membership.return_value = replace(self.original, role="admin")
        changed = self.ensure(role="invalid")
        self.assert_identity_preserved(changed)
        self.assertEqual(changed.role, "member")
        self.store.get_membership.return_value = changed
        self.store.save_membership.reset_mock()
        self.assertEqual(self.ensure(role="another-invalid"), changed)
        self.store.save_membership.assert_not_called()

    def test_inactive_membership_is_reactivated_without_replacing_identity(self):
        self.store.get_membership.return_value = replace(self.original, status="inactive")
        changed = self.ensure()
        self.assert_identity_preserved(changed)
        self.assertEqual(changed.status, "active")
        self.assertEqual(changed.updated_at, self.now + timedelta(days=1))
