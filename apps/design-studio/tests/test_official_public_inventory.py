"""Public-API-only canonical inventory proofs."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from official_public_inventory import (  # noqa: E402
    _inventory,
    _inventory_with_identity_sets,
    _inventory_with_preservation_sets,
)


class FakePublicApi:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def get_json(self, path: str) -> dict:
        self.paths.append(path)
        payloads = {
            "/api/projects": {
                "projects": [
                    {
                        "id": "project-1",
                        "name": "Secret project",
                        "status": {"value": "completed", "runId": "run-1"},
                    }
                ]
            },
            "/api/projects/project-1": {
                "project": {"id": "project-1", "name": "Secret project", "createdAt": 1}
            },
            "/api/projects/project-1/conversations": {
                "conversations": [{"id": "conversation-1", "createdAt": 1}]
            },
            "/api/projects/project-1/conversations/conversation-1/messages": {
                "messages": [
                    {
                        "id": "message-1",
                        "content": "Secret transcript",
                        "runId": "run-1",
                        "runStatus": "completed",
                        "lastRunEventId": 7,
                    }
                ]
            },
            "/api/projects/project-1/files": {
                "files": [
                    {
                        "path": "design.html",
                        "size": 14,
                        "artifactManifest": {"title": "Secret artifact"},
                    }
                ]
            },
            "/api/live-artifacts?projectId=project-1": {
                "artifacts": [{"id": "artifact-1", "title": "Secret live artifact"}]
            },
            "/api/live-artifacts/artifact-1?projectId=project-1": {
                "artifact": {"id": "artifact-1", "template": "Secret template"}
            },
            "/api/design-systems": {
                "designSystems": [
                    {"id": "preset", "source": "built-in", "title": "Preset"},
                    {"id": "user:brand", "source": "user", "title": "Secret brand"},
                ]
            },
            "/api/design-systems/user%3Abrand": {
                "designSystem": {"id": "user:brand", "title": "Secret brand"}
            },
            "/api/design-systems/user%3Abrand/files": {
                "files": [
                    {"path": "tokens", "name": "tokens", "kind": "folder"},
                    {
                        "path": "tokens/colors.css",
                        "name": "colors.css",
                        "kind": "code",
                        "size": 20,
                        "updatedAt": "unstable",
                    },
                ]
            },
            "/api/design-systems/user%3Abrand/file?path=tokens%2Fcolors.css": {
                "file": {"path": "tokens/colors.css", "content": "Secret brand CSS"}
            },
            "/api/app-config": {"config": {"theme": "system"}},
            "/api/runs": {
                "runs": [
                    {
                        "id": "run-1",
                        "status": "completed",
                        "projectId": "project-1",
                        "pid": 999,
                        "eventsLogPath": "/private",
                    }
                ]
            },
        }
        return payloads[path]

    def get_bytes(self, path: str) -> bytes:
        self.paths.append(path)
        payloads = {
            "/api/projects/project-1/files/design.html": b"Secret HTML",
            "/api/live-artifacts/artifact-1/preview?projectId=project-1&variant=template": b"Secret template",
            "/api/live-artifacts/artifact-1/preview?projectId=project-1&variant=rendered-source": b"Secret rendered",
        }
        return payloads[path]


class OfficialPublicInventoryTests(unittest.TestCase):
    def test_supported_apis_cover_every_cutover_category_without_retaining_content(self) -> None:
        client = FakePublicApi()

        inventory = _inventory(client)

        self.assertEqual(
            {key: value["count"] for key, value in inventory.items()},
            {
                "projects": 1,
                "conversations": 1,
                "ordered_messages": 1,
                "design_systems": 2,
                "project_files": 1,
                "artifacts": 2,
                "settings": 1,
                "run_references": 3,
            },
        )
        rendered = str(inventory)
        for secret in ("Secret project", "Secret transcript", "Secret HTML", "Secret brand"):
            self.assertNotIn(secret, rendered)
        self.assertTrue(all(path.startswith("/api/") for path in client.paths))
        self.assertFalse(any("sqlite" in path or "database" in path for path in client.paths))

    def test_preservation_identities_are_complete_redaction_safe_hashes(self) -> None:
        categories, identities = _inventory_with_identity_sets(FakePublicApi())

        self.assertEqual(set(identities), set(categories))
        for category, values in identities.items():
            self.assertEqual(len(values), categories[category]["count"])
            self.assertEqual(values, sorted(values))
            self.assertTrue(
                all(
                    len(value) == 64
                    and all(character in "0123456789abcdef" for character in value)
                    for value in values
                )
            )
        rendered = str(identities)
        for secret in ("Secret project", "Secret transcript", "Secret HTML", "Secret brand"):
            self.assertNotIn(secret, rendered)

    def test_content_preservation_hashes_detect_mutation_without_exposing_content(self) -> None:
        baseline = FakePublicApi()
        _categories, identities, content = _inventory_with_preservation_sets(baseline)
        migrated = FakePublicApi()
        original_get_json = migrated.get_json

        def emptied_message(path: str) -> dict:
            payload = original_get_json(path)
            if path.endswith("/messages"):
                payload["messages"][0]["content"] = ""
            return payload

        migrated.get_json = emptied_message  # type: ignore[method-assign]
        _next_categories, next_identities, next_content = _inventory_with_preservation_sets(migrated)

        self.assertEqual(identities, next_identities)
        self.assertNotEqual(content["ordered_messages"], next_content["ordered_messages"])
        self.assertEqual(set(content), set(_categories))
        rendered = str(content)
        self.assertNotIn("Secret transcript", rendered)


if __name__ == "__main__":
    unittest.main()
