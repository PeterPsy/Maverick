from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_pwa_cache import REPOSITORY_ROOT, audit_frontend_manifests, audit_repository


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


if __name__ == "__main__":
    unittest.main()
