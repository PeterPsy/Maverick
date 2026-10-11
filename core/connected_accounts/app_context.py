"""Project a selected personal account into a trusted app invocation."""

from dataclasses import replace
from pathlib import Path

from core.connected_accounts.google import available_services
from core.connected_accounts.service import digest, public_account
from core.identity.errors import UserNotFoundError
from core.workspaces.errors import WorkspaceMembershipError


def account_context(*, identity_store, workspace_store, permissions, user_id, workspace_id, app_id, data_root):
    store = getattr(identity_store, "account_store", None)
    declaration = permissions.external_accounts.get("google")
    if not store or not declaration or not user_id or not workspace_store:
        return None
    try:
        user = identity_store.get_user(user_id)
        membership = workspace_store.get_membership(user_id=user_id, workspace_id=workspace_id)
    except (UserNotFoundError, WorkspaceMembershipError):
        return None
    if not user.is_active or membership.status != "active":
        return None
    selection = store.get_selection(user_id, workspace_id)
    if not selection or app_id in selection.disabled_apps:
        return None
    account = store.get_account(selection.account_id)
    if not account or account.user_id != user_id or account.provider != "google":
        return None
    root = Path(data_root) / "connected-accounts" / digest(user_id)[:24] / account.account_id
    # Data roots are host-owned input. Refuse symlinks before creating or using
    # the private subtree, including app-created intermediate directories.
    current = Path(data_root)
    for part in root.relative_to(current).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Personal account data roots may not contain symlinks.")
    root.mkdir(parents=True, exist_ok=True)
    capabilities = sorted(set(declaration.capabilities) & set(available_services(account.scopes)))
    return {"account": account, "services": capabilities, "data_root": str(root),
            "replaces_secrets": declaration.replaces_secrets, "selection": selection}


def filter_secret_requests(requests, context):
    if context is None:
        return requests
    replaced = set(context["replaces_secrets"])
    return [replace(request, logical_names=[name for name in request.logical_names if name not in replaced])
            for request in requests if any(name not in replaced for name in request.logical_names)]


def account_payload(context):
    if context is None:
        return []
    return [{**public_account(context["account"]), "services": context["services"],
             "scopes": context["account"].scopes, "managed_by": "platform"}]
