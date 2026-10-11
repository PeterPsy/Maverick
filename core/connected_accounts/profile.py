"""Hydrate display photos for existing consented accounts without new authority."""

from datetime import UTC, datetime, timedelta

from core.app_sdk.google_profile import google_picture_url
from core.connected_accounts import google
from core.secrets.errors import SecretError

USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
PROFILE_SCOPES = {"profile", "https://www.googleapis.com/auth/userinfo.profile"}


def refresh_profile(account, *, account_store, secret_store, now=None):
    timestamp = now or datetime.now(UTC)
    if (account.provider != "google" or account.status != "connected" or not account.secret_ref
            or google_picture_url(account.picture_url) or not PROFILE_SCOPES.intersection(account.scopes)
            or account.profile_checked_at and timestamp - account.profile_checked_at < timedelta(days=1)):
        return account
    # Claim the attempt before network I/O to coalesce concurrent app reads and
    # back off for accounts whose consent cannot supply a profile photo.
    claimed = account_store.update_profile(account, picture_url="", checked_at=timestamp)
    if claimed is None:
        return account_store.get_account(account.account_id) or account
    try:
        client_id, client_secret = google.credentials(secret_store)
        tokens = google.json_request(google.TOKEN_URL, data={"client_id": client_id,
            "client_secret": client_secret, "refresh_token": google.secret_value(secret_store, account.secret_ref),
            "grant_type": "refresh_token"})
        token = tokens.get("access_token")
        if not isinstance(token, str) or not token:
            return claimed
        profile = google.json_request(USERINFO_URL, headers={"Authorization": "Bearer " + token})
        if profile.get("sub") != account.subject:
            return claimed
        picture = google_picture_url(profile.get("picture"))
        if picture:
            return account_store.update_profile(claimed, picture_url=picture, checked_at=timestamp) or claimed
    except (google.AccountError, SecretError):
        # A missing photo must not interrupt Calendar, Mail, Drive or sign-in.
        pass
    return claimed
