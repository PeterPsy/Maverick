"""Development defaults must satisfy the normal password contract."""

import os
import unittest
from unittest.mock import patch

from core.api.platform_state import _bootstrap_admin_credentials
from core.identity.service import authenticate_password, create_user, set_user_password
from core.identity.store import IdentityCollections, IdentityDocumentStore
from tests.support.collections import FakeCollection


class BootstrapTestCredentialsTest(unittest.TestCase):
    def test_insecure_test_default_can_create_and_update_a_password(self):
        with patch.dict(os.environ, {"LOOPINO_ALLOW_INSECURE_TEST_DEFAULTS": "1"}, clear=True):
            username, password = _bootstrap_admin_credentials()
        store = IdentityDocumentStore(IdentityCollections(
            users=FakeCollection(), credentials=FakeCollection(), auth_sessions=FakeCollection(),
        ))
        user = create_user(store, username=username, password=password)
        set_user_password(store, user_id=user.user_id, password=password)
        self.assertEqual(
            authenticate_password(store, username=username, password=password).user_id,
            user.user_id,
        )
