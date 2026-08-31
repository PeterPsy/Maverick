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
from official_update_state import migration_preservation_guard  # noqa: E402


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

    def test_protected_identities_are_redaction_safe_and_exclude_builtins(self) -> None:
        categories, identities = _inventory_with_identity_sets(FakePublicApi())

        self.assertEqual(set(identities), set(categories))
        for category, values in identities.items():
            if category == "design_systems":
                self.assertEqual(len(values), 1)
                self.assertLess(len(values), categories[category]["count"])
            else:
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

    def test_adjacent_plain_text_event_chunks_are_semantically_equivalent(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def chunked_message(path: str) -> dict:
            payload = baseline_get_json(path)
            if path.endswith("/messages"):
                payload["messages"][0]["events"] = [
                    {"kind": "text", "text": "Secret "},
                    {"kind": "text", "text": "transcript"},
                ]
            return payload

        baseline.get_json = chunked_message  # type: ignore[method-assign]
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def coalesced_message(path: str) -> dict:
            payload = migrated_get_json(path)
            if path.endswith("/messages"):
                payload["messages"][0]["events"] = [
                    {"kind": "text", "text": "Secret transcript"},
                ]
            return payload

        migrated.get_json = coalesced_message  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )
        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertNotEqual(
            baseline_categories["ordered_messages"],
            migrated_categories["ordered_messages"],
        )
        self.assertEqual(
            baseline_content["ordered_messages"],
            migrated_content["ordered_messages"],
        )
        self.assertEqual(guard["state"], "passed")

    def test_text_event_content_or_metadata_loss_remains_protected(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def message_with_metadata(path: str) -> dict:
            payload = baseline_get_json(path)
            if path.endswith("/messages"):
                payload["messages"][0]["events"] = [
                    {"kind": "text", "text": "Secret ", "sequence": 1},
                    {"kind": "text", "text": "transcript", "sequence": 2},
                ]
            return payload

        baseline.get_json = message_with_metadata  # type: ignore[method-assign]
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def lossy_message(path: str) -> dict:
            payload = migrated_get_json(path)
            if path.endswith("/messages"):
                payload["messages"][0]["events"] = [
                    {"kind": "text", "text": "Secret changed", "sequence": 1},
                ]
            return payload

        migrated.get_json = lossy_message  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )
        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(guard["state"], "failed")
        self.assertGreater(guard["lost_content_counts"]["ordered_messages"], 0)

    def test_project_functional_metadata_loss_fails_content_guard(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def project_with_functional_metadata(path: str) -> dict:
            payload = baseline_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {
                    "entryFile": "design.html",
                    "kind": "website",
                    "voice": "warm",
                    "media": {"template": "hero"},
                }
            return payload

        baseline.get_json = project_with_functional_metadata  # type: ignore[method-assign]
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def project_without_metadata(path: str) -> dict:
            payload = migrated_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {}
            return payload

        migrated.get_json = project_without_metadata  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(baseline_identities, migrated_identities)
        self.assertEqual(guard["state"], "failed")
        self.assertGreater(guard["lost_content_counts"]["projects"], 0)

    def test_future_project_field_loss_fails_without_an_inventory_code_change(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def project_with_future_field(path: str) -> dict:
            payload = baseline_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["futureFunctionalConfiguration"] = {
                    "layoutMode": "editorial",
                }
            return payload

        baseline.get_json = project_with_future_field  # type: ignore[method-assign]
        migrated = FakePublicApi()
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(baseline_identities, migrated_identities)
        self.assertEqual(guard["state"], "failed")
        self.assertGreater(guard["lost_content_counts"]["projects"], 0)

    def test_future_list_only_project_field_loss_fails_content_guard(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def project_list_with_future_field(path: str) -> dict:
            payload = baseline_get_json(path)
            if path == "/api/projects":
                payload["projects"][0]["futureListConfiguration"] = {
                    "preferredCanvas": "wide",
                }
            return payload

        baseline.get_json = project_list_with_future_field  # type: ignore[method-assign]
        migrated = FakePublicApi()
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(baseline_identities, migrated_identities)
        self.assertEqual(guard["state"], "failed")
        self.assertGreater(guard["lost_content_counts"]["projects"], 0)

    def test_project_list_run_status_is_explicitly_server_owned(self) -> None:
        baseline = FakePublicApi()
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def project_list_with_new_run_status(path: str) -> dict:
            payload = migrated_get_json(path)
            if path == "/api/projects":
                payload["projects"][0]["status"]["value"] = "running"
            return payload

        migrated.get_json = project_list_with_new_run_status  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(guard["state"], "passed")
        self.assertEqual(baseline_content["projects"], migrated_content["projects"])

    def test_empty_project_containers_have_presence_and_type_claims(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def project_with_empty_container(path: str) -> dict:
            payload = baseline_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {"explicitPanels": []}
            return payload

        baseline.get_json = project_with_empty_container  # type: ignore[method-assign]
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def project_without_empty_container(path: str) -> dict:
            payload = migrated_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {}
            return payload

        migrated.get_json = project_without_empty_container  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(baseline_identities, migrated_identities)
        self.assertEqual(guard["state"], "failed")
        self.assertGreater(guard["lost_content_counts"]["projects"], 0)

        changed_type = FakePublicApi()
        changed_type_get_json = changed_type.get_json

        def project_with_changed_empty_container_type(path: str) -> dict:
            payload = changed_type_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {"explicitPanels": {}}
            return payload

        changed_type.get_json = (  # type: ignore[method-assign]
            project_with_changed_empty_container_type
        )
        changed_categories, changed_identities, changed_content = (
            _inventory_with_preservation_sets(changed_type)
        )
        type_guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(changed_categories, changed_identities, changed_content),
        )
        self.assertEqual(type_guard["state"], "failed")
        self.assertGreater(type_guard["lost_content_counts"]["projects"], 0)

    def test_content_guard_allows_volatile_metadata_and_additive_schema_changes(self) -> None:
        baseline = FakePublicApi()
        baseline_get_json = baseline.get_json

        def legacy_metadata(path: str) -> dict:
            payload = baseline_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {
                    "entryFile": "design.html",
                    "kind": "website",
                    "updatedAt": "before",
                    "resolvedDir": "/old/server/path",
                }
            return payload

        baseline.get_json = legacy_metadata  # type: ignore[method-assign]
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def compatible_migration(path: str) -> dict:
            payload = migrated_get_json(path)
            if path == "/api/projects/project-1":
                payload["project"]["metadata"] = {
                    "entryFile": "design.html",
                    "kind": "website",
                    "updatedAt": "after",
                    "resolvedDir": "/new/server/path",
                    "media": {"voice": "warm"},
                }
                payload["project"]["serverComputedField"] = "new-schema"
            if path == "/api/design-systems":
                payload["designSystems"][0]["title"] = "Updated built-in preset"
            if path == "/api/design-systems/user%3Abrand":
                payload["designSystem"]["newSchemaField"] = "additive"
            return payload

        migrated.get_json = compatible_migration  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(guard["state"], "passed")
        self.assertFalse(any(guard["lost_content_counts"].values()))
        self.assertGreater(guard["added_content_counts"]["projects"], 0)
        self.assertGreater(guard["added_content_counts"]["design_systems"], 0)

    def test_builtin_design_system_removal_or_rename_is_release_owned(self) -> None:
        baseline = FakePublicApi()
        migrated = FakePublicApi()
        migrated_get_json = migrated.get_json

        def renamed_builtin(path: str) -> dict:
            payload = migrated_get_json(path)
            if path == "/api/design-systems":
                payload["designSystems"][0] = {
                    "id": "replacement-preset",
                    "source": "built-in",
                    "title": "Replacement preset",
                }
            return payload

        migrated.get_json = renamed_builtin  # type: ignore[method-assign]
        baseline_categories, baseline_identities, baseline_content = (
            _inventory_with_preservation_sets(baseline)
        )
        migrated_categories, migrated_identities, migrated_content = (
            _inventory_with_preservation_sets(migrated)
        )

        guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(migrated_categories, migrated_identities, migrated_content),
        )

        self.assertEqual(
            baseline_identities["design_systems"],
            migrated_identities["design_systems"],
        )
        self.assertEqual(guard["state"], "passed")
        self.assertEqual(guard["lost_identity_counts"]["design_systems"], 0)

        removed = FakePublicApi()
        removed_get_json = removed.get_json

        def removed_builtin(path: str) -> dict:
            payload = removed_get_json(path)
            if path == "/api/design-systems":
                payload["designSystems"] = payload["designSystems"][1:]
            return payload

        removed.get_json = removed_builtin  # type: ignore[method-assign]
        removed_categories, removed_identities, removed_content = (
            _inventory_with_preservation_sets(removed)
        )
        removal_guard = migration_preservation_guard(
            _inventory_payload(baseline_categories, baseline_identities, baseline_content),
            _inventory_payload(removed_categories, removed_identities, removed_content),
        )

        self.assertEqual(removal_guard["state"], "passed")
        self.assertEqual(removal_guard["lost_identity_counts"]["design_systems"], 0)


def _inventory_payload(categories: dict, identities: dict, content: dict) -> dict:
    return {
        "categories": categories,
        "identity_sets": identities,
        "content_sets": content,
    }


if __name__ == "__main__":
    unittest.main()
