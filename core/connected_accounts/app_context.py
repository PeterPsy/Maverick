"""Project workspace-enabled personal accounts into a trusted app invocation."""

from dataclasses import replace
from pathlib import Path

from core.connected_accounts.google import available_services
from core.connected_accounts.service import digest, public_account
from core.identity.errors import UserNotFoundError
from core.workspaces.errors import WorkspaceMembershipError


def account_context(*, identity_store, workspace_store, permissions, user_id, workspace_id, app_id, data_root, account_id=None):
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
    if not selection:
        return None
    parent = Path(data_root) / "connected-accounts" / digest(user_id)[:24]
    root = _private_path(data_root, parent / "shared")
    root.mkdir(parents=True, exist_ok=True)
    accounts = []
    if app_id not in selection.disabled_apps:
        for selected_id in dict.fromkeys([selection.account_id, *selection.account_ids]):
            if selected_id not in selection.account_ids or (account_id and selected_id != account_id):
                continue
            account = store.get_account(selected_id)
            if not account or account.user_id != user_id or account.provider != "google":
                continue
            capabilities = sorted(set(declaration.capabilities) & set(available_services(account.scopes)))
            accounts.append({"account": account, "services": capabilities,
                "previous_data_root": str(_private_path(data_root, parent / account.account_id))})
    selected = next(iter(accounts), {"account": None, "services": []})
    return {**selected, "accounts": accounts, "data_root": str(root), "workspace_data_root": str(data_root),
            "replaces_secrets": declaration.replaces_secrets, "selection": selection}


def _private_path(data_root, root):
    # Data roots are host-owned input. Refuse symlinks before creating or using
    # the private subtree, including app-created intermediate directories.
    current = Path(data_root)
    for part in root.relative_to(current).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Personal account data roots may not contain symlinks.")
    return root


def filter_secret_requests(requests, context):
    if context is None:
        return requests
    replaced = set(context["replaces_secrets"])
    return [replace(request, logical_names=[name for name in request.logical_names if name not in replaced])
            for request in requests if any(name not in replaced for name in request.logical_names)]


def account_payload(context):
    if context is None:
        return []
    return [{**public_account(item["account"]), "services": item["services"],
             "scopes": item["account"].scopes, "managed_by": "platform",
             "default": item["account"].account_id == context["selection"].account_id,
             "previous_data_root": item["previous_data_root"]} for item in context["accounts"]]
