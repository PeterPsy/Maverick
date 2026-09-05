from __future__ import annotations

import json
from pathlib import Path
from typing import get_args
import unittest

from core.providers.agentic_models import RuntimeDataClass


ROOT = Path(__file__).resolve().parents[3]
INVENTORY_PATH = ROOT / "docs" / "product" / "pwa_cache_resource_inventory.v2.json"
CANONICAL_DATA_CLASSES = set(get_args(RuntimeDataClass))
LOCAL_PERSISTENCE_POLICIES = ("deny", "session", "cache")
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
OPTIONAL_FIELDS = {
    "cache_approved",
    "invalidation_aliases",
    "policy_prerequisites",
    "privacy_approved",
    "regulated_allowlisted",
    "runtime_schema_revision",
}


class PwaResourceInventoryTests(unittest.TestCase):
    def test_inventory_is_versioned_complete_and_bounded(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "maverick.pwa-cache-resource-inventory.v2")
        self.assertEqual(payload["policy_revision"], "maverick.local-persistence-policy.v2")
        self.assertIs(payload["resource_schema_revision_required"], True)
        self.assertEqual(
            payload["private_app_origin_boundary"],
            "isolated_origin_and_exact_frame_parent_broker",
        )
        self.assertEqual(payload["canonical_data_class_source"], "core.providers.agentic_models.RuntimeDataClass")
        self.assertEqual(payload["local_persistence_policy_values"], list(LOCAL_PERSISTENCE_POLICIES))
        self.assertEqual(payload["unknown_classification_policy"], "deny")
        resources = payload["resources"]
        self.assertGreaterEqual(len(resources), 20)
        identities: set[tuple[tuple[str, ...], str]] = set()
        for resource in resources:
            fields = set(resource)
            self.assertEqual(REQUIRED_FIELDS - fields, set())
            self.assertEqual(fields - REQUIRED_FIELDS - OPTIONAL_FIELDS, set())
            identity = (tuple(resource["app_ids"]), resource["resource"])
            self.assertNotIn(identity, identities)
            identities.add(identity)
            self.assertTrue(resource["owner"])
            self.assertTrue(resource["revision"])
            self.assertTrue(resource["invalidation"])
            self.assertIn(resource["canonical_data_class"], CANONICAL_DATA_CLASSES)
            self.assertIn(resource["local_persistence_policy"], LOCAL_PERSISTENCE_POLICIES)
            prerequisites = resource.get("policy_prerequisites", [])
            self.assertIsInstance(prerequisites, list)
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in prerequisites))
            for field in ("cache_approved", "privacy_approved", "regulated_allowlisted"):
                if field in resource:
                    self.assertIsInstance(resource[field], bool)
            if "runtime_schema_revision" in resource:
                self.assertIsInstance(resource["runtime_schema_revision"], str)
                self.assertTrue(resource["runtime_schema_revision"].strip())
                aliases = resource.get("invalidation_aliases")
                self.assertIsInstance(aliases, list)
                self.assertTrue(aliases)
                self.assertEqual(len(aliases), len(set(aliases)))
                self.assertTrue(
                    all(isinstance(alias, str) and alias == alias.strip() and alias for alias in aliases)
                )
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

    def test_deny_rows_cannot_allocate_local_ttl_or_bytes(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

        for resource in payload["resources"]:
            if resource["local_persistence_policy"] == "deny":
                self.assertEqual(resource["fresh_ttl_seconds"], 0)
                self.assertEqual(resource["expiry_ttl_seconds"], 0)
                self.assertEqual(resource["max_entry_bytes"], 0)
                self.assertEqual(resource["max_scope_bytes"], 0)

    def test_unclassified_resources_fail_closed(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

        for resource in payload["resources"]:
            if resource["canonical_data_class"] == "unclassified":
                self.assertEqual(resource["local_persistence_policy"], "deny")

    def test_inventory_contains_no_obsolete_network_absence_policy(self) -> None:
        text = INVENTORY_PATH.read_text(encoding="utf-8").lower()

        self.assertNotIn("offline_opt_in", text)
        self.assertNotIn("offline-file", text)
        self.assertNotIn("user opt-in", text)
        self.assertNotIn("outbox", text)

    def test_m5_pilot_contracts_match_the_parent_broker_declarations(self) -> None:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        resources = {
            (resource["app_ids"][0], resource["resource"]): resource
            for resource in payload["resources"]
            if len(resource["app_ids"]) == 1
        }
        expected = {
            ("website-studio", "site-snapshots"): ("cache", 60, 86_400, 2_097_152, 16_777_216),
            ("storage", "file-catalog"): ("cache", 30, 86_400, 262_144, 16_777_216),
            ("app-store", "catalog"): ("cache", 300, 86_400, 1_048_576, 4_194_304),
            ("fitness-coach", "sanitized-bootstrap-and-thumbnails"): (
                "cache", 300, 86_400, 524_288, 16_777_216
            ),
        }

        expected.update({
            ("calendar", "bounded-event-window"): ("cache", 60, 21600, 1048576, 16777216),
            ("chat", "projects-and-completed-messages"): ("cache", 30, 21600, 1048576, 33554432),
            ("crm", "lists-and-recent-records"): ("cache", 30, 21600, 2097152, 16777216),
            ("mail", "thread-headers-snippets-and-bodies"): ("cache", 30, 3600, 1048576, 16777216),
        })

        for identity, contract in expected.items():
            resource = resources[identity]
            self.assertEqual(
                (
                    resource["local_persistence_policy"],
                    resource["fresh_ttl_seconds"],
                    resource["expiry_ttl_seconds"],
                    resource["max_entry_bytes"],
                    resource["max_scope_bytes"],
                ),
                contract,
            )
            self.assertIn("default-off", resource["rollout"])


if __name__ == "__main__":
    unittest.main()
