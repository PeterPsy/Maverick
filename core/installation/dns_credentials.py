"""Authorized private DNS credential projection for the installation issuer."""

import os
from pathlib import Path
import re
import tempfile

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.store import SecretDocumentStore
from core.shared.installation_material import dns_credentials_root

ROOT = Path(__file__).resolve().parents[2]
SECRET_REF = "platform:secret-alias/cloudflare-dns-api-token"


def resolve_token(secret_ref: str = SECRET_REF) -> str:
    """Use Core's authorized platform delivery, without bootstrapping the host."""
    collections = build_control_plane_collections(
        ControlStoreSettings.from_environment(repository_root=ROOT)
    )
    return resolve_secret_for_runtime(
        SecretDocumentStore(collections.secrets),
        context=SecretResolutionContext(
            workspace_id=None, operator_request=True, platform_delivery=True,
            allow_unbound_secret_refs=True, action="installation.tls.dns01",
            target="https://api.cloudflare.com/client/v4/",
        ),
        secret_ref=secret_ref,
    ).value


def validate_token(token: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,256}", token):
        raise ValueError("Invalid Cloudflare API token format")
    return token


def refresh_credentials(path: Path, *, resolver=resolve_token) -> None:
    """Replace the private runtime projection, discarding any stale credential."""
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("An absolute non-symlink credential path is required")
    if path.parent != dns_credentials_root(ROOT):
        raise ValueError("Credentials must stay in the designated installation TLS credential directory")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    # Certbot does not abort on a failed pre-hook. Remove the old projection
    # first so a disabled/revoked/missing Vault secret cannot be reused.
    path.unlink(missing_ok=True)
    token = validate_token(resolver())
    handle, temporary = tempfile.mkstemp(prefix=".cloudflare-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write("dns_cloudflare_api_token = " + token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
