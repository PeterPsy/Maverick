"""Recoverable mutations limited to the two installation-owned DNS names."""

import json
from pathlib import Path

from core.installation.cloudflare import dns_changes
from core.installation.private_state import write_private
from core.installation.errors import InstallationError

FIELDS = {"type", "name", "content", "ttl", "proxied", "priority", "data", "comment", "tags"}


def delegation_ready(service, job: dict, plan: dict) -> dict:
    provider = service.dns_factory(service.secret_store, plan["dns_secret_ref"], actor_user_id=job["actor_user_id"])
    zone = provider.zone(plan["hostname"])
    if zone["id"] != plan["zone"]["id"]:
        raise InstallationError("dns_zone_changed", status=409)
    return {"waiting": zone["status"] != "active", "nameservers": zone.get("name_servers", [])}


def apply_dns(service, job: dict, plan: dict, private: Path) -> dict:
    provider = service.dns_factory(service.secret_store, plan["dns_secret_ref"], actor_user_id=job["actor_user_id"])
    zone = provider.zone(plan["hostname"])
    if zone["id"] != plan["zone"]["id"]:
        raise InstallationError("dns_zone_changed", status=409)
    if zone["status"] != "active":
        return {"waiting": True, "nameservers": zone["name_servers"]}
    snapshot = private / "dns-before.json"
    marker = "Loopino job " + job["job_id"]
    if not snapshot.exists():
        records = provider.records(zone["id"])
        changes = dns_changes(plan["hostname"], plan["target_ip"], records)
        # A plan cannot silently take over a record edited since it was reviewed.
        expected = {item["name"]: item for item in plan["dns_changes"]}
        for item in changes:
            if item["action"] != "keep" and (item["action"] != expected[item["name"]]["action"]
                    or item.get("before", []) != expected[item["name"]].get("before", [])):
                raise InstallationError("dns_records_changed_since_plan", status=409)
        write_private(snapshot, {"zone_id": zone["id"], "changes": changes})
    backup = json.loads(snapshot.read_text())
    for item in backup["changes"]:
        if item["action"] == "keep":
            continue
        records = [record for record in provider.records(zone["id"]) if record["name"] == item["name"]
                   and record["type"] in {"A", "AAAA", "CNAME"}]
        owned = [record for record in records if record.get("comment") == marker]
        if owned:
            if len(records) != 1 or any(owned[0].get(key) != value for key, value in item["after"].items()):
                raise InstallationError("dns_record_ownership_conflict", status=409)
            continue
        original_ids = {record["id"] for record in item.get("before", [])}
        if any(record["id"] not in original_ids for record in records):
            raise InstallationError("dns_record_ownership_conflict", status=409)
        for record in records:
            provider.delete(zone["id"], record["id"])
        provider.create(zone["id"], {**item["after"], "comment": marker})
    return {"waiting": False, "zone_id": zone["id"]}


def restore_dns(service, original_job: dict, plan: dict, private: Path) -> None:
    snapshot = private / "dns-before.json"
    if not snapshot.exists():
        return
    provider = service.dns_factory(service.secret_store, plan["dns_secret_ref"], actor_user_id=original_job["actor_user_id"])
    backup = json.loads(snapshot.read_text())
    marker = "Loopino job " + original_job["job_id"]
    operations = []
    for item in backup["changes"]:
        if item["action"] == "keep":
            continue
        current = [record for record in provider.records(backup["zone_id"]) if record["name"] == item["name"]
                   and record["type"] in {"A", "AAAA", "CNAME"}]
        before = item.get("before", [])
        signature = lambda record: {key: value for key, value in record.items() if key in FIELDS}
        remaining = [signature(record) for record in before]
        owned = []
        for record in current:
            if record.get("comment") == marker:
                owned.append(record)
            elif signature(record) in remaining:
                remaining.remove(signature(record))
            else:
                raise InstallationError("dns_rollback_conflict", status=409)
        operations.append((owned, remaining))
    for owned, remaining in operations:
        for record in owned:
            provider.delete(backup["zone_id"], record["id"])
        for record in remaining:
            provider.create(backup["zone_id"], record)
