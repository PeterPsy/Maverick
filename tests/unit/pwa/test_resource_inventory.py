from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
INVENTORY_PATH = ROOT / "docs" / "product" / "pwa_cache_resource_inventory.v1.json"
REQUIRED_FIELDS = {
    "app_ids",
    "resource",
    "owner",
    "read_surface",
    "canonical_data_class",
    "provenance",
    "local_persistence_policy",
    "fresh_ttl_seconds",
    "expiry_ttl_seconds",
    "revision",
    "max_entry_bytes",
    "max_scope_bytes",
    "invalidation",
    "data_event",
    "rollout",
}


class PwaResourceInventoryTests(unittest.TestCase):
    def test_inventory_is_versioned_complete_and_bounded(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "maverick.pwa-cache-resource-inventory.v1")
        self.assertEqual(payload["policy_revision"], "maverick.local-persistence-policy.v1")
        resources = payload["resources"]
        self.assertGreaterEqual(len(resources), 20)
        identities: set[tuple[tuple[str, ...], str]] = set()
        for resource in resources:
            self.assertEqual(set(resource), REQUIRED_FIELDS)
            identity = (tuple(resource["app_ids"]), resource["resource"])
            self.assertNotIn(identity, identities)
            identities.add(identity)
            self.assertTrue(resource["owner"])
            self.assertTrue(resource["revision"])
            self.assertTrue(resource["invalidation"])
            for field in ("fresh_ttl_seconds", "expiry_ttl_seconds", "max_entry_bytes", "max_scope_bytes"):
                self.assertIsInstance(resource[field], int)
                self.assertGreaterEqual(resource[field], 0)

    def test_every_built_in_app_is_owned_by_at_least_one_inventory_row(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        inventoried = {
            app_id
            for resource in payload["resources"]
            for app_id in resource["app_ids"]
            if app_id != "core-control-plane"
        }
        built_in_apps = {
            path.parent.name
            for path in (ROOT / "apps").glob("*/app_contract.json")
        }

        self.assertEqual(built_in_apps - inventoried, set())

    def test_deny_rows_cannot_allocate_persistent_bytes(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

        for resource in payload["resources"]:
            if resource["local_persistence_policy"] == "deny":
                self.assertEqual(resource["max_entry_bytes"], 0)
                self.assertEqual(resource["max_scope_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
