#!/usr/bin/env python3
"""Deliver a Vault credential to Certbot; never emit secret values."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.store import SecretDocumentStore
from core.shared.env_file import read_env_file

SECRET_REF = "platform:secret-alias/cloudflare-dns-api-token"
DEFAULT_CREDENTIALS = Path("/etc/letsencrypt/maverick/cloudflare.ini")


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
    if path == ROOT or ROOT in path.parents:
        raise ValueError("Credentials must stay outside the repository")
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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cloudflare_get(token: str, endpoint: str) -> dict:
    request = Request("https://api.cloudflare.com/client/v4/" + endpoint,
                      headers={"Authorization": "Bearer " + validate_token(token)})
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        result = json.load(response)
    if not result.get("success"):
        raise RuntimeError("Cloudflare API request failed")
    return result


def inspect_zone(zone_id: str, *, resolver=resolve_token, getter=cloudflare_get) -> dict:
    """Inspect public DNS metadata and a record digest without making edits."""
    if not re.fullmatch(r"[a-f0-9]{32}", zone_id):
        raise ValueError("Invalid zone ID")
    token = validate_token(resolver())
    zone = getter(token, "zones/" + zone_id)["result"]
    records = []
    page = 1
    while True:
        result = getter(token, f"zones/{zone_id}/dns_records?per_page=100&page={page}")
        records.extend(result["result"])
        if page >= result.get("result_info", {}).get("total_pages", 1):
            break
        page += 1
    # API timestamps and identifiers are not part of DNS behavior.
    projections = [{key: record.get(key) for key in
                    ("name", "type", "content", "priority", "ttl", "proxied", "data")}
                   for record in records]
    serialized = sorted(json.dumps(record, sort_keys=True) for record in projections)
    return {
        "zone": zone["name"], "zone_status": zone["status"],
        "nameservers": zone["name_servers"], "record_count": len(records),
        "records_sha256": hashlib.sha256("\n".join(serialized).encode()).hexdigest(),
        "records": [{key: record.get(key) for key in ("name", "type", "proxied")}
                    for record in records],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--inspect-zone", metavar="ZONE_ID")
    parser.add_argument("--secret-ref", default=SECRET_REF)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("Root privileges are required for installation TLS delivery")
    try:
        if not args.env_file.is_file():
            raise FileNotFoundError("Installation environment is missing")
        os.environ.update(read_env_file(args.env_file))
        os.chdir(ROOT)
        if args.inspect_zone:
            result = inspect_zone(args.inspect_zone)
        else:
            from core.installation.validation import secret_ref
            reference = secret_ref(args.secret_ref)
            refresh_credentials(args.credentials, resolver=lambda: resolve_token(reference))
            result = {"credentials": str(args.credentials), "secret_ref": reference}
        print(json.dumps({"status": "ready", **result}))
        return 0
    except Exception as error:
        # Exception strings/tracebacks may contain credentials from dependencies.
        print(json.dumps({"status": "blocked", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
