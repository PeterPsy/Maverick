from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_pwa_cache import (
    INVENTORY_PATH,
    POLICY_PATH,
    RUNTIME_RESOURCE_DECLARATIONS_PATH,
    REPOSITORY_ROOT,
    audit_ci_hardening,
    audit_frontend_manifests,
    audit_repository,
    audit_resource_inventory,
    audit_runtime_resource_declarations,
    production_retry_audit_ids,
)


class PwaCacheAuditTests(unittest.TestCase):
    def test_repository_operational_policy_is_self_consistent(self) -> None:
        self.assertEqual(audit_repository(REPOSITORY_ROOT), [])

    def test_frontend_asset_budget_rejects_an_oversized_new_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = root / "apps" / "example" / "frontend" / "dist"
            build.mkdir(parents=True)
            body = b"12345"
            (build / "index.html").write_bytes(body)
            record = {
                "path": "index.html",
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
            (build / "maverick-frontend-assets.json").write_text(
                json.dumps(
                    {
                        "schema": "maverick.frontend-assets.v2",
                        "build_id": "a" * 12,
                        "entrypoints": ["index.html"],
                        "immutable": [],
                        "revalidated": [record],
                    }
                ),
                encoding="utf-8",
            )
            errors: list[str] = []

            audit_frontend_manifests(
                root,
                {
                    "asset_budgets": {
                        "max_frontend_asset_bytes": 4,
                        "max_frontend_manifest_bytes": 100,
                        "max_shell_precache_bytes": 100,
                    }
                },
                errors,
            )

            self.assertTrue(any("asset size 5 exceeds 4" in error for error in errors), errors)

    def test_frontend_asset_budget_covers_unmanifested_builds_and_undeclared_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "apps" / "legacy" / "frontend" / "dist"
            legacy.mkdir(parents=True)
            (legacy / "index.html").write_bytes(b"12345")
            errors: list[str] = []
            policy = {
                "asset_budgets": {
                    "max_frontend_asset_bytes": 4,
                    "max_frontend_manifest_bytes": 100,
                    "max_shell_precache_bytes": 100,
                }
            }

            audit_frontend_manifests(root, policy, errors)

            self.assertTrue(any("legacy/frontend/dist: asset size 5 exceeds 4" in error for error in errors), errors)
            self.assertTrue(any("no committed frontend asset manifests" in error for error in errors), errors)

            example = root / "apps" / "example" / "frontend" / "dist"
            example.mkdir(parents=True)
            body = b"ok"
            (example / "index.html").write_bytes(body)
            (example / "extra.js").write_bytes(b"x")
            (example / "maverick-frontend-assets.json").write_text(
                json.dumps(
                    {
                        "schema": "maverick.frontend-assets.v2",
                        "build_id": "a" * 12,
                        "entrypoints": ["index.html"],
                        "immutable": [],
                        "revalidated": [{
                            "path": "index.html",
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "size_bytes": len(body),
                        }],
                    }
                ),
                encoding="utf-8",
            )
            errors = []

            audit_frontend_manifests(root, policy, errors)

            self.assertTrue(any("undeclared build outputs: extra.js" in error for error in errors), errors)

    def test_resource_inventory_rejects_unknown_and_fail_closed_cache_classes(self) -> None:
        policy = json.loads((REPOSITORY_ROOT / POLICY_PATH).read_text(encoding="utf-8"))
        inventory = json.loads((REPOSITORY_ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))

        for data_class in (
            "host_operational_metadata",
            "regulated_or_customer_data",
            "future_unknown_class",
        ):
            with self.subTest(data_class=data_class):
                candidate = deepcopy(inventory)
                resource = candidate["resources"][0]
                resource["canonical_data_class"] = data_class
                resource["local_persistence_policy"] = "cache"
                errors: list[str] = []

                audit_resource_inventory(candidate, policy, errors)

                self.assertTrue(
                    any(data_class in error or "unknown canonical data class" in error for error in errors),
                    errors,
                )

    def test_resource_policy_must_enumerate_every_canonical_class(self) -> None:
        policy = json.loads((REPOSITORY_ROOT / POLICY_PATH).read_text(encoding="utf-8"))
        inventory = json.loads((REPOSITORY_ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))
        del policy["data_class_persistence"]["host_operational_metadata"]
        errors: list[str] = []

        audit_resource_inventory(inventory, policy, errors)

        self.assertTrue(any("complete canonical class set" in error for error in errors), errors)

    def test_runtime_resource_declarations_must_match_inventory_contracts(self) -> None:
        inventory = json.loads((REPOSITORY_ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))
        declarations = json.loads(
            (REPOSITORY_ROOT / RUNTIME_RESOURCE_DECLARATIONS_PATH).read_text(encoding="utf-8")
        )
        candidate = deepcopy(declarations)
        candidate["resources"][0]["max_entry_bytes"] += 1
        errors: list[str] = []

        audit_runtime_resource_declarations(inventory, candidate, errors)

        self.assertTrue(any("max_entry_bytes" in error and "inventory" in error for error in errors), errors)

    def test_runtime_resource_declarations_enumerate_every_canonical_class(self) -> None:
        inventory = json.loads((REPOSITORY_ROOT / INVENTORY_PATH).read_text(encoding="utf-8"))
        declarations = json.loads(
            (REPOSITORY_ROOT / RUNTIME_RESOURCE_DECLARATIONS_PATH).read_text(encoding="utf-8")
        )
        declarations["canonical_data_classes"].remove("host_operational_metadata")
        errors: list[str] = []

        audit_runtime_resource_declarations(inventory, declarations, errors)

        self.assertTrue(any("canonical_data_classes" in error for error in errors), errors)

    def test_retry_source_discovery_covers_javascript_and_shared_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_source = root / "packages" / "shared-client" / "src" / "retry.js"
            package_source.parent.mkdir(parents=True)
            package_source.write_text(
                """export const mutation = {
  auditId: 'shared-client.retry-write.v1',
  serverDeduplicates: true,
};
""",
                encoding="utf-8",
            )
            storage_source = root / "apps" / "storage" / "frontend" / "src" / "retry.ts"
            storage_source.parent.mkdir(parents=True)
            storage_source.write_text(
                """export const mutation = {
  auditId: 'storage.retry-write.v1',
  serverDeduplicates: true,
};
""",
                encoding="utf-8",
            )
            errors: list[str] = []

            discovered = production_retry_audit_ids(root, errors)

            self.assertEqual(
                discovered,
                {"shared-client.retry-write.v1", "storage.retry-write.v1"},
            )
            self.assertEqual(errors, [])

    def test_retry_source_discovery_rejects_javascript_contract_without_audit_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "apps" / "example" / "client" / "retry.mjs"
            source.parent.mkdir(parents=True)
            source.write_text("export const mutation = { serverDeduplicates: true };\n", encoding="utf-8")
            errors: list[str] = []

            self.assertEqual(production_retry_audit_ids(root, errors), set())
            self.assertTrue(any("requires one literal auditId" in error for error in errors), errors)

    def test_ci_hardening_requires_sdk_settings_smoke_and_physical_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yml").write_text("jobs: {}\n", encoding="utf-8")
            (workflows / "pwa-physical-device-gate.yml").write_text("jobs: {}\n", encoding="utf-8")
            errors: list[str] = []

            audit_ci_hardening(root, errors)

            self.assertTrue(any("pwa-cache run typecheck" in error for error in errors), errors)
            self.assertTrue(any("apps/settings test" in error for error in errors), errors)
            self.assertTrue(any("physical-device workflow" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
