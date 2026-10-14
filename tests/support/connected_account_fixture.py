"""Identity/account setup shared by Core and app integration tests."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from core.api.session_api import RequestSession
from core.connected_accounts.google import SERVICES
from core.connected_accounts.service import complete_flow, start_flow
from core.connected_accounts.store import AccountCollections, AccountDocumentStore
from core.identity.service import build_auth_session, build_user_record
from core.identity.store import IdentityCollections, IdentityDocumentStore
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.shared.in_memory_collection import InMemoryCollection
from core.workspaces.service import build_workspace_record, ensure_workspace_membership
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore

ROOT = Path(__file__).resolve().parents[2]

class ConnectedAccountFixture(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.accounts = AccountDocumentStore(AccountCollections(*(InMemoryCollection() for _ in range(3))))
        self.identity = IdentityDocumentStore(IdentityCollections(*(InMemoryCollection() for _ in range(3))), account_store=self.accounts)
        self.workspace = WorkspaceDocumentStore(WorkspaceCollections(*(InMemoryCollection() for _ in range(5))))
        self.workspace.save_workspace(build_workspace_record(workspace_id="default", name="Default", slug="default", now=self.now))
        self.user = self.identity.save_user(build_user_record(user_id="user:alice", username="alice", email="alice@example.com", now=self.now))
        ensure_workspace_membership(self.workspace, membership_id="alice-default", workspace_id="default", user_id=self.user.user_id, role="member", now=self.now)
        session = build_auth_session(session_id="session-alice", user_id=self.user.user_id, expires_at=self.now + timedelta(days=1), now=self.now)
        self.context = RequestSession(self.user, session, "default")
        self.secrets = SecretDocumentStore(SecretCollections(*(InMemoryCollection() for _ in range(4))), key_loader=lambda: b"k" * 32)
        create_platform_secret(self.secrets, label="Client id", secret_id="client-id", alias="google-oauth-client-id", raw_value="test-client")
        create_platform_secret(self.secrets, label="Client secret", secret_id="client-secret", alias="google-oauth-client-secret", raw_value="private-client-secret")
        self.state = SimpleNamespace(account_store=self.accounts, identity_store=self.identity, workspace_store=self.workspace,
                                     secret_store=self.secrets, repository_root=ROOT)
        self.environment = patch.dict("os.environ", {"LOOPINO_GOOGLE_REDIRECT_URI": "https://loopino.example/api/auth/google/callback",
            "LOOPINO_GOOGLE_ALLOW_REGISTRATION": "1", "LOOPINO_GOOGLE_CLIENT_ID_REF": "platform:secret-alias/google-oauth-client-id",
            "LOOPINO_GOOGLE_CLIENT_SECRET_REF": "platform:secret-alias/google-oauth-client-secret"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def flow(self, services=None, mode="connect", context=None):
        result, browser = start_flow(self.state, mode=mode, services=services or [],
                                     context=self.context if mode == "connect" and context is None else context, now=self.now)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        return query, browser

    def complete(self, query, browser, *, context=None, subject="subject-alice", email="alice@example.com", scopes=None, refresh="private-refresh"):
        tokens = {"id_token": "signed-token", "scope": " ".join(scopes if scopes is not None else SERVICES["calendar"]["scopes"]), "refresh_token": refresh}
        return complete_flow(self.state, raw_state=query["state"][0], browser=browser, code="auth-code",
            context=context or self.context, now=self.now, exchange=lambda *args, **kwargs: tokens,
            identity_verifier=lambda *args, **kwargs: {"sub": subject, "email": email, "name": "Alice"})
