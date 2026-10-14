#!/usr/bin/env python3
"""Deliver a Vault credential to Certbot; never emit secret values."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.installation.dns_credentials import SECRET_REF, resolve_token, validate_token, refresh_credentials
from core.shared.env_file import read_env_file, service_env_path
from core.shared.installation_material import dns_credentials_root

DEFAULT_CREDENTIALS = dns_credentials_root(ROOT) / "cloudflare.ini"


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
    parser.add_argument("--env-file", type=Path, default=service_env_path(ROOT))
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
        with contextlib.chdir(ROOT):
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
