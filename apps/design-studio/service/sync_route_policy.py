#!/usr/bin/env python3
"""Synchronize Design Studio's exact browser policy with the pinned route inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parent
APP_ROOT = SERVICE_ROOT.parent
INVENTORY_PATH = SERVICE_ROOT / "opendesign_routes_0_16_1.json"
CONTRACT_PATH = APP_ROOT / "app_contract.json"

_STATIC_RULES = (
    {"method": "GET", "path_template": "/"},
    {"method": "GET", "path_template": "/_next", "static_tree": True},
    {"method": "GET", "path_template": "/artifacts", "static_tree": True},
    {"method": "GET", "path_template": "/assets", "static_tree": True},
    {"method": "GET", "path_template": "/favicon.ico"},
    {"method": "GET", "path_template": "/frames", "static_tree": True},
    {"method": "GET", "path_template": "/index.html"},
    {"method": "GET", "path_template": "/projects/{id}"},
)
_MAVERICK_EXTENSION_RULES = (
    ("pass_through", {"method": "GET", "path_template": "/api/maverick-ready"}),
    # The upstream raw route is multi-segment and therefore remains blocked.
    # Maverick exposes only the exact one-segment read used to verify a bounded
    # Storage import; nested project exports use the governed batch archive API.
    ("pass_through", {"method": "GET", "path_template": "/api/projects/{id}/raw/{name}"}),
    ("handled_by_core", {"method": "POST", "path_template": "/api/export/storage"}),
    ("handled_by_core", {"method": "POST", "path_template": "/api/import/storage"}),
)


def expected_route_policy(inventory: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return the exact contract policy implied by the authoritative inventory."""
    if inventory.get("schema_version") != "1" or not isinstance(inventory.get("routes"), list):
        raise ValueError("OpenDesign route inventory is malformed.")
    grouped: dict[str, dict[tuple[str, str, bool], dict[str, Any]]] = {
        "pass_through": {},
        "handled_by_core": {},
        "blocked": {},
    }
    for route in inventory["routes"]:
        classification = str(route.get("classification") or "")
        method = str(route.get("method") or "")
        template = str(route.get("path_template") or "")
        if classification not in grouped:
            raise ValueError(f"Unknown route classification `{classification}`.")
        if method == "USE":
            if classification == "pass_through" and template not in {"/artifacts", "/frames"}:
                raise ValueError(f"Unexpected authorized middleware route `{template}`.")
            continue
        if "{*" in template:
            if classification != "blocked":
                raise ValueError(f"Multi-segment route `{method} {template}` must be blocked.")
            continue
        rule = {"method": method, "path_template": template}
        grouped[classification][_rule_key(rule)] = rule
    for rule in _STATIC_RULES:
        grouped["pass_through"][_rule_key(rule)] = dict(rule)
    for classification, rule in _MAVERICK_EXTENSION_RULES:
        grouped[classification][_rule_key(rule)] = dict(rule)
    return {
        classification: sorted(rules.values(), key=_rule_key)
        for classification, rules in grouped.items()
    }


def _rule_key(rule: dict[str, Any]) -> tuple[str, str, bool]:
    return (
        str(rule.get("path_template") or ""),
        str(rule.get("method") or ""),
        bool(rule.get("static_tree", False)),
    )


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _contract_sidecar(contract: dict[str, Any]) -> dict[str, Any]:
    sidecars = contract.get("services", {}).get("http_sidecars", [])
    matches = [item for item in sidecars if isinstance(item, dict) and item.get("id") == "opendesign"]
    if len(matches) != 1:
        raise ValueError("Design Studio must declare exactly one `opendesign` sidecar.")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write the derived policy instead of checking it.")
    args = parser.parse_args()
    inventory = _load(INVENTORY_PATH)
    expected = expected_route_policy(inventory)
    contract = _load(CONTRACT_PATH)
    sidecar = _contract_sidecar(contract)
    current = sidecar.get("proxy", {}).get("route_policy")
    if args.write:
        sidecar["proxy"]["route_policy"] = expected
        CONTRACT_PATH.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        return 0
    if current != expected:
        raise SystemExit(
            "Design Studio route policy differs from the 0.16.1 inventory; "
            "run sync_route_policy.py --write and review the generated diff."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
