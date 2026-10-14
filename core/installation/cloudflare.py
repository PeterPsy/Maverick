"""Zone-scoped DNS operations through Core-controlled secret delivery."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from core.installation.errors import InstallationError
from core.installation.validation import record_id, secret_ref
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime

BASE = "https://api.cloudflare.com/client/v4/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CloudflareDns:
    def __init__(self, store, credential_ref: str, *, actor_user_id=None):
        self.store, self.credential_ref = store, secret_ref(credential_ref)
        self.actor_user_id = actor_user_id

    def request(self, method: str, endpoint: str, body=None) -> dict:
        if not endpoint.startswith("zones") or ".." in endpoint or ":" in endpoint:
            raise InstallationError("invalid_dns_operation")
        try:
            lease = resolve_secret_for_runtime(self.store, secret_ref=self.credential_ref,
                context=SecretResolutionContext(workspace_id=None, platform_delivery=True,
                    operator_request=True, allow_unbound_secret_refs=True,
                    action="installation.dns." + method.lower(), target=BASE,
                    actor_user_id=self.actor_user_id))
            request = Request(BASE + endpoint, method=method,
                headers={"Authorization": "Bearer " + lease.value, "Content-Type": "application/json"},
                data=json.dumps(body).encode() if body is not None else None)
            with build_opener(NoRedirect).open(request, timeout=20) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise InstallationError("dns_response_too_large")
            data = json.loads(raw)
            if not data.get("success"):
                raise InstallationError("dns_provider_rejected_request", status=502)
            return data
        except InstallationError:
            raise
        except HTTPError as error:
            raise InstallationError("dns_access_denied" if error.code in {401, 403} else "dns_provider_unavailable", status=502) from None
        except (URLError, OSError, ValueError):
            raise InstallationError("dns_provider_unavailable", status=502) from None

    def zone(self, host: str) -> dict:
        labels = host.split(".")
        for offset in range(len(labels) - 1):
            name = ".".join(labels[offset:])
            result = self.request("GET", "zones?" + urlencode({"name": name}))["result"]
            if result:
                zone = result[0]
                return {key: zone[key] for key in ("id", "name", "status", "name_servers")}
        raise InstallationError("dns_zone_not_authorized")

    def records(self, zone_id: str) -> list[dict]:
        record_id(zone_id)
        records, page = [], 1
        while True:
            result = self.request("GET", f"zones/{zone_id}/dns_records?per_page=100&page={page}")
            records.extend(result["result"])
            if page >= result.get("result_info", {}).get("total_pages", 1):
                return records
            page += 1
            if page > 100:
                raise InstallationError("dns_zone_inventory_too_large")

    def create(self, zone_id: str, record: dict) -> dict:
        return self.request("POST", f"zones/{record_id(zone_id)}/dns_records", record)["result"]

    def update(self, zone_id: str, identifier: str, record: dict) -> dict:
        return self.request("PUT", f"zones/{record_id(zone_id)}/dns_records/{record_id(identifier)}", record)["result"]

    def delete(self, zone_id: str, identifier: str) -> None:
        self.request("DELETE", f"zones/{record_id(zone_id)}/dns_records/{record_id(identifier)}")


def token_template(zone: dict) -> str:
    return "https://dash.cloudflare.com/profile/api-tokens?" + urlencode({
        "permissionGroupKeys": json.dumps([{"key": "dns", "type": "edit"}, {"key": "zone", "type": "read"}], separators=(",", ":")),
        "accountId": "*", "zoneId": zone["id"], "name": "Loopino DNS"})


def dns_changes(host: str, address: str, records: list[dict]) -> list[dict]:
    kind = "AAAA" if ":" in address else "A"
    changes = []
    for name in (host, "*.sidecars." + host):
        exact = [record for record in records if record["name"] == name and record["type"] in {"A", "AAAA", "CNAME"}]
        if len(exact) == 1 and exact[0]["type"] == kind and exact[0]["content"] == address and not exact[0].get("proxied"):
            changes.append({"action": "keep", "name": name, "record": exact[0]})
            continue
        # DNS wildcard expansion stops at the closest existing node, including
        # empty nonterminals established by TXT/MX or deeper records.
        nodes = {".".join(record["name"].split(".")[offset:])
                 for record in records for offset in range(len(record["name"].split(".")))}
        if not exact and name not in nodes:
            ancestors = [".".join(name.split(".")[offset:]) for offset in range(1, len(name.split(".")))]
            closest = next((ancestor for ancestor in ancestors if ancestor in nodes), None)
            inherited = [record for record in records if record["name"] == "*." + str(closest)
                         and record["type"] in {"A", "AAAA", "CNAME"}]
            if (len(inherited) == 1 and inherited[0]["type"] == kind
                    and inherited[0]["content"] == address and not inherited[0].get("proxied")):
                changes.append({"action": "keep", "name": name, "record": inherited[0]})
                continue
        changes.append({"action": "replace" if exact else "create", "name": name,
                        "before": exact, "after": {"type": kind, "name": name, "content": address, "ttl": 300, "proxied": False}})
    return changes
