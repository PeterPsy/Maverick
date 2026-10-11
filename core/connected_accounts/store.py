"""Control-plane persistence for federated identity and OAuth consent."""

from dataclasses import asdict, dataclass
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from core.identity.store import DocumentCollection
from core.connected_accounts.models import AccountSelection, ConnectedAccount, OAuthFlow


class AccountStore(Protocol):
    def get_account(self, account_id: str) -> ConnectedAccount | None: ...
    def find_subject(self, provider: str, subject: str) -> ConnectedAccount | None: ...
    def list_accounts(self, user_id: str) -> list[ConnectedAccount]: ...
    def save_account(self, account: ConnectedAccount) -> ConnectedAccount: ...
    def claim_account(self, account: ConnectedAccount) -> ConnectedAccount: ...
    def get_selection(self, user_id: str, workspace_id: str) -> AccountSelection | None: ...
    def save_selection(self, selection: AccountSelection) -> AccountSelection: ...
    def update_selection(self, user_id: str, workspace_id: str, updater: Callable) -> AccountSelection: ...
    def save_flow(self, flow: OAuthFlow) -> None: ...
    def consume_flow(self, state_hash: str, browser_hash: str, now) -> OAuthFlow | None: ...
    def get_flow(self, state_hash: str) -> OAuthFlow | None: ...
    def transition_flow(self, flow: OAuthFlow, expected_status: str) -> bool: ...


@dataclass(frozen=True)
class AccountCollections:
    accounts: DocumentCollection
    selections: DocumentCollection
    flows: DocumentCollection


class AccountDocumentStore:
    def __init__(self, collections: AccountCollections):
        self.collections = collections

    def get_account(self, account_id):
        item = self.collections.accounts.find_one({"account_id": account_id})
        return ConnectedAccount(**item) if item else None

    def find_subject(self, provider, subject):
        item = self.collections.accounts.find_one({"provider": provider, "subject": subject})
        return ConnectedAccount(**item) if item else None

    def list_accounts(self, user_id):
        return [ConnectedAccount(**item) for item in self.collections.accounts.find({"user_id": user_id})]

    def save_account(self, account):
        self.collections.accounts.update_one({"account_id": account.account_id}, {"$set": asdict(account)}, upsert=True)
        return account

    def claim_account(self, account):
        from core.connected_accounts.google import AccountError
        existing, inserted = self.collections.accounts.insert_one_if_absent(
            {"provider": account.provider, "subject": account.subject}, asdict(account))
        if not inserted and existing["user_id"] != account.user_id:
            raise AccountError("google_account_already_linked", status=409)
        return account if inserted else self.save_account(account)

    def get_selection(self, user_id, workspace_id):
        item = self.collections.selections.find_one({"user_id": user_id, "workspace_id": workspace_id})
        return _selection(item)

    def update_selection(self, user_id, workspace_id, updater):
        from core.connected_accounts.google import AccountError
        collection = self.collections.selections
        identity = {"user_id": user_id, "workspace_id": workspace_id}
        for _ in range(32):
            original = collection.find_one(identity)
            updated = updater(_selection(original))
            if original is None:
                _, inserted = collection.insert_one_if_absent(identity, asdict(updated))
                if inserted:
                    return updated
            elif collection.compare_and_set({**original, "account_ids": original.get("account_ids")}, {"$set": asdict(updated)}):
                return updated
        raise AccountError("account_selection_conflict", status=409)

    def save_selection(self, selection):
        self.collections.selections.update_one({"selection_id": selection.selection_id}, {"$set": asdict(selection)}, upsert=True)
        return selection

    def save_flow(self, flow):
        now = datetime.now(UTC)
        for item in self.collections.flows.find({}):
            if item["expires_at"] <= now:
                self.collections.flows.delete_one({"state_hash": item["state_hash"]})
        self.collections.flows.update_one({"state_hash": flow.state_hash}, {"$set": asdict(flow)}, upsert=True)

    def consume_flow(self, state_hash, browser_hash, now):
        query = {"state_hash": state_hash, "browser_hash": browser_hash, "status": "pending"}
        item = self.collections.flows.find_one(query)
        if not item or item["expires_at"] <= now:
            return None
        if not self.collections.flows.compare_and_set(query, {"$set": {"status": "consumed"}}):
            return None
        return OAuthFlow(**item)

    def get_flow(self, state_hash):
        item = self.collections.flows.find_one({"state_hash": state_hash})
        return OAuthFlow(**item) if item else None

    def transition_flow(self, flow, expected_status):
        return self.collections.flows.compare_and_set(
            {"state_hash": flow.state_hash, "status": expected_status}, {"$set": asdict(flow)})


def _selection(item):
    # Upgrade the original single-account selection without enabling any
    # additional personal accounts in an existing workspace.
    if item and "account_ids" not in item:
        item = {**item, "account_ids": [item["account_id"]] if item["account_id"] else []}
    return AccountSelection(**item) if item else None
