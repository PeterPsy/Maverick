"""App contract tests for app-owned HTTP sidecar services."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contract_serializer import app_contract_payload
from core.apps.contracts import parse_app_contract_file
from core.apps.errors import AppContractValidationError
from core.apps.store import AppCollections, AppDocumentStore
from tests.contracts.app_contract.sidecar_contract_fixture import SidecarContractFixture


def _contract_store() -> AppDocumentStore:
    collections = AppCollections(
        app_sources=None,  # type: ignore[arg-type]
        workspace_local_app_projects=None,  # type: ignore[arg-type]
        workspace_app_bindings=None,  # type: ignore[arg-type]
        workspace_app_sidecar_quarantines=None,  # type: ignore[arg-type]
        workspace_app_dependency_selections=None,  # type: ignore[arg-type]
    )
    return AppDocumentStore(collections)


class AppContractServiceTests(SidecarContractFixture, unittest.TestCase):
    def test_parse_contract_accepts_governed_http_sidecar(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))

            loaded = parse_app_contract_file(app_root)
            payload = app_contract_payload(loaded)

            self.assertEqual(loaded.contract.services.http_sidecars[0].service_id, "opendesign")
            self.assertEqual(loaded.contract.services.http_sidecars[0].bind.port, "auto")
            self.assertEqual(loaded.contract.services.http_sidecars[0].process_policy.sandbox, "required")
            self.assertEqual(loaded.contract.services.http_sidecars[0].process_policy.transport, "unix_relay")
            self.assertEqual(loaded.contract.services.http_sidecars[0].process_policy.outbound, [])
            self.assertEqual(loaded.contract.services.http_sidecars[0].process_policy.limits.request_concurrency, 16)
            self.assertEqual(
                loaded.contract.services.http_sidecars[0].artifact_mounts[0].mount_path,
                "/artifacts/opendesign",
            )
            self.assertEqual(
                loaded.contract.services.http_sidecars[0].root_filesystem.subpath,
                "official/release/rootfs",
            )
            self.assertTrue(loaded.contract.services.http_sidecars[0].prewarm.on_core_start)
            self.assertEqual(loaded.contract.services.http_sidecars[0].browser_origin.mode, "isolated")
            self.assertEqual(loaded.contract.services.http_sidecars[0].browser_origin.frame_ancestors, ["platform"])
            self.assertEqual(
                loaded.contract.services.http_sidecars[0].browser_origin.immutable_asset_prefixes,
                ["/_next/static/"],
            )
            self.assertEqual(
                loaded.contract.services.http_sidecars[0].browser_origin.sandboxed_frame_resource_prefixes,
                ["/api/plugins/", "/api/asset-cache"],
            )
            self.assertEqual(loaded.contract.services.http_sidecars[0].entrypoint_access.ttl_seconds, 30)
            self.assertEqual(
                [surface.surface for surface in loaded.contract.services.http_sidecars[0].entrypoint_access.surfaces],
                ["backend", "cli", "mcp", "reference"],
            )
            self.assertEqual(loaded.contract.services.http_sidecars[0].proxy.route_policy.blocked[0].path_template, "/api/import/folder")
            self.assertFalse(loaded.contract.permissions.providers.model_proxy)
            self.assertEqual(loaded.contract.permissions.providers.credential_source, "none")
            self.assertFalse(loaded.contract.permissions.providers.deliver_secrets_to_app)
            self.assertEqual(json.loads((app_root / "app_contract.json").read_text(encoding="utf-8")), payload)

            persisted = asdict(loaded.contract)
            restored = _contract_store()._app_contract(persisted)
            restored_sidecar = restored.services.http_sidecars[0]
            self.assertEqual(
                restored_sidecar.proxy.route_policy.pass_through[3].path_template,
                "/api/projects/{id}",
            )
            self.assertEqual(
                restored_sidecar.entrypoint_access.surfaces[2].routes[0].path_template,
                "/api/projects/{id}",
            )
            self.assertEqual(restored_sidecar.root_filesystem.subpath, "official/release/rootfs")
            self.assertEqual(
                restored_sidecar.browser_origin.sandboxed_frame_resource_prefixes,
                ["/api/plugins/", "/api/asset-cache"],
            )

    def test_artifact_root_filesystem_is_bounded_to_a_declared_namespace(self) -> None:
        mutations = (
            ({"artifact_id": "missing", "subpath": "official/release/rootfs"}, "artifact mount"),
            ({"artifact_id": "opendesign", "subpath": "../rootfs"}, "canonical path"),
            ({"artifact_id": "opendesign", "subpath": "/rootfs"}, "canonical path"),
        )
        for root_filesystem, expected in mutations:
            with self.subTest(root_filesystem=root_filesystem), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["root_filesystem"] = root_filesystem
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(AppContractValidationError, expected):
                    parse_app_contract_file(app_root)

    def test_parse_contract_accepts_provider_model_proxy_permission(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["permissions"]["providers"] = {
                "model_proxy": True,
                "credential_source": "core-vault",
                "deliver_secrets_to_app": False,
            }
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            loaded = parse_app_contract_file(app_root)

            self.assertTrue(loaded.contract.permissions.providers.model_proxy)
            self.assertEqual(loaded.contract.permissions.providers.credential_source, "core-vault")
            self.assertFalse(loaded.contract.permissions.providers.deliver_secrets_to_app)

    def test_model_access_is_explicit_optional_and_round_trips(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["permissions"]["providers"] = {
                "model_proxy": True,
                "credential_source": "core-vault",
                "deliver_secrets_to_app": False,
            }
            payload["services"]["http_sidecars"][0]["model_access"] = {
                "api": True,
                "cli": ["codex"],
                "required": False,
            }
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            loaded = parse_app_contract_file(app_root)
            model_access = loaded.contract.services.http_sidecars[0].model_access

            self.assertIsNotNone(model_access)
            assert model_access is not None
            self.assertTrue(model_access.api)
            self.assertEqual(model_access.cli, ["codex"])
            self.assertFalse(model_access.required)
            self.assertEqual(app_contract_payload(loaded)["services"]["http_sidecars"][0]["model_access"], payload["services"]["http_sidecars"][0]["model_access"])

            restored = _contract_store()._app_contract(asdict(loaded.contract))
            self.assertEqual(restored.services.http_sidecars[0].model_access, model_access)

    def test_model_access_requires_model_proxy_and_cannot_block_native_startup(self) -> None:
        mutations = (
            ({"api": True, "cli": [], "required": False}, "model_proxy"),
            ({"api": True, "cli": [], "required": True}, "required.*must be false"),
            ({"api": False, "cli": [], "required": False}, "request API or CLI"),
        )
        for model_access, expected in mutations:
            with self.subTest(model_access=model_access), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                if model_access.get("required") is True or not model_access.get("api"):
                    payload["permissions"]["providers"] = {
                        "model_proxy": True,
                        "credential_source": "core-vault",
                        "deliver_secrets_to_app": False,
                    }
                payload["services"]["http_sidecars"][0]["model_access"] = model_access
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(AppContractValidationError, expected):
                    parse_app_contract_file(app_root)

    def test_scoped_data_mount_and_host_prepare_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            (app_root / "hooks").mkdir()
            (app_root / "hooks" / "prepare.py").write_text("print('{}')\n", encoding="utf-8")
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            sidecar = payload["services"]["http_sidecars"][0]
            sidecar["data_mount"] = {"subpath": "opendesign-native"}
            sidecar["host_prepare"] = {
                "entrypoint": "hooks/prepare.py",
                "timeout_seconds": 30,
                "environment_keys": ["LOOPINO_APP_LAUNCH_CONFIGURATION"],
            }
            (app_root / "app_contract.json").write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )

            loaded = parse_app_contract_file(app_root)
            parsed_sidecar = loaded.contract.services.http_sidecars[0]

            self.assertEqual(parsed_sidecar.data_mount.subpath, "opendesign-native")
            self.assertEqual(
                parsed_sidecar.host_prepare.environment_keys,
                ["LOOPINO_APP_LAUNCH_CONFIGURATION"],
            )
            self.assertEqual(
                app_contract_payload(loaded)["services"]["http_sidecars"][0]["data_mount"],
                sidecar["data_mount"],
            )
            restored = _contract_store()._app_contract(asdict(loaded.contract))
            self.assertEqual(restored.services.http_sidecars[0].data_mount, parsed_sidecar.data_mount)
            self.assertEqual(restored.services.http_sidecars[0].host_prepare, parsed_sidecar.host_prepare)

    def test_scoped_data_mount_and_host_prepare_fail_closed(self) -> None:
        mutations = (
            ("data_mount", {"subpath": "../delegations"}, "canonical path"),
            (
                "host_prepare",
                {
                    "entrypoint": "service/server.py",
                    "timeout_seconds": 30,
                    "environment_keys": ["OD_API_TOKEN"],
                },
                "app-owned key",
            ),
        )
        for field, value, expected in mutations:
            with self.subTest(field=field), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0][field] = value
                (app_root / "app_contract.json").write_text(
                    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(AppContractValidationError, expected):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_unknown_provider_credential_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["permissions"]["providers"] = {
                "model_proxy": True,
                "credential_source": "direct-env",
                "deliver_secrets_to_app": True,
            }
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "credential_source"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_exposed_sidecar_without_route_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            del payload["services"]["http_sidecars"][0]["proxy"]["route_policy"]
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "route_policy"):
                parse_app_contract_file(app_root)

    def test_route_policy_requires_exact_templates_and_methods_for_authorized_routes(self) -> None:
        mutations = (
            ({"method": "GET", "path_prefix": "/api/projects"}, "path_prefix"),
            ({"path_template": "/api/projects/{id}"}, "method"),
            ({"method": "POST", "path_template": "/api/projects/{*}"}, "must be named"),
            ({"method": "GET", "path_template": "/api/projects", "static_tree": True}, "outside"),
        )
        for replacement, expected in mutations:
            with self.subTest(replacement=replacement), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["proxy"]["route_policy"]["pass_through"][0] = replacement
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, expected):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_sandbox_sidecar_without_process_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            del payload["services"]["http_sidecars"][0]["process_policy"]
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "process_policy.*required"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_weakened_sandbox_process_policy(self) -> None:
        mutations = (
            ("inherit_host_env", True),
            ("sandbox", "optional"),
            ("bundle_read_only", False),
            ("workspace_data_write", False),
            ("network", "host"),
            ("transport", "tcp_loopback"),
            ("outbound", ["https://example.invalid"]),
        )
        for field, value in mutations:
            with self.subTest(field=field), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["process_policy"][field] = value
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, field):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_forbidden_or_unresolved_sandbox_environment(self) -> None:
        mutations = (
            ("HOME", "/operator-home"),
            ("OPENAI_API_KEY", "provider-secret"),
            ("LOOPINO_BOOTSTRAP_SECRET", "bootstrap-secret"),
            ("ARBITRARY", "${host.secret}"),
            ("WORKSPACE", "${workspace.root}"),
        )
        for key, value in mutations:
            with self.subTest(key=key), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["env"][key] = value
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, "env"):
                    parse_app_contract_file(app_root)

    def test_artifact_mounts_are_platform_owned_and_substitutions_are_declared(self) -> None:
        mutations = (
            (lambda sidecar: sidecar["artifact_mounts"][0].__setitem__("mount_path", "/app/vendor"), "platform-owned"),
            (lambda sidecar: sidecar["artifact_mounts"].append(dict(sidecar["artifact_mounts"][0])), "Duplicate"),
            (lambda sidecar: sidecar["env"].__setitem__("EXTRA", "${artifact.unknown}"), "substitution"),
            (lambda sidecar: sidecar["prewarm"].__setitem__("keep_alive", False), "keep_alive"),
        )
        for mutate, expected in mutations:
            with self.subTest(expected=expected), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                mutate(payload["services"]["http_sidecars"][0])
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, expected):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_weakened_browser_origin_policy(self) -> None:
        mutations = (
            ("mode", "shared"),
            ("csp_profile", "permissive"),
            ("frame_ancestors", ["*"]),
            ("connect_src", ["self", "https://example.invalid"]),
        )
        for field, value in mutations:
            with self.subTest(field=field), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["browser_origin"][field] = value
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, field):
                    parse_app_contract_file(app_root)

    def test_browser_font_origins_round_trip_without_granting_api_egress(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text())
            origin = payload["services"]["http_sidecars"][0]["browser_origin"]
            origin["style_origins"] = ["https://fonts.googleapis.com"]
            origin["font_origins"] = ["https://fonts.gstatic.com"]
            (app_root / "app_contract.json").write_text(json.dumps(payload))

            loaded = parse_app_contract_file(app_root)
            restored = _contract_store()._app_contract(asdict(loaded.contract))
            sidecar = restored.services.http_sidecars[0]
            self.assertEqual(sidecar.browser_origin.style_origins, origin["style_origins"])
            self.assertEqual(sidecar.browser_origin.font_origins, origin["font_origins"])
            self.assertEqual(app_contract_payload(loaded), payload)
            self.assertEqual(sidecar.browser_origin.connect_src, ["self"])
            self.assertEqual(sidecar.process_policy.outbound, [])

    def test_browser_font_origins_reject_ambiguous_or_injected_sources(self) -> None:
        invalid = (
            ["*"], ["https:"], ["http://fonts.example"],
            ["https://*.example.com"], ["https://fonts.example/path"],
            ["https://fonts.example?query=1"], ["https://fonts.example#fragment"],
            ["https://user@fonts.example"], ["https://fonts.example; script-src *"],
            ["https://fonts.example\\evil"], ["https://fonts.example:bad"],
            ["https://fonts.example:65536"], ["https://fonts.example:0"],
            ["https://fonts.example", "https://fonts.example"],
            [f"https://fonts{i}.example" for i in range(9)],
        )
        for field in ("style_origins", "font_origins"):
            for value in invalid:
                with self.subTest(field=field, value=value), TemporaryDirectory() as temp_dir:
                    app_root = self._write_sidecar_app(Path(temp_dir))
                    payload = json.loads((app_root / "app_contract.json").read_text())
                    payload["services"]["http_sidecars"][0]["browser_origin"][field] = value
                    (app_root / "app_contract.json").write_text(json.dumps(payload))
                    with self.assertRaisesRegex(AppContractValidationError, field):
                        parse_app_contract_file(app_root)

    def test_restoring_font_origins_rejects_unsafe_persisted_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            loaded = parse_app_contract_file(self._write_sidecar_app(Path(temp_dir)))
            persisted = asdict(loaded.contract)
            origin = persisted["services"]["http_sidecars"][0]["browser_origin"]
            for field in ("style_origins", "font_origins"):
                with self.subTest(field=field):
                    origin[field] = ["https://fonts.example; script-src *"]
                    with self.assertRaisesRegex(AppContractValidationError, field):
                        _contract_store()._app_contract(persisted)
                    origin[field] = []

    def test_parse_contract_rejects_unsafe_immutable_asset_prefixes(self) -> None:
        invalid_values = (
            ["/"],
            ["/api/static/"],
            ["/.well-known/assets/"],
            ["/_next/static"],
            ["/_next//static/"],
            ["/_next/%2e%2e/"],
            ["/_next/static/", "/_next/static/"],
        )
        for value in invalid_values:
            with self.subTest(value=value), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["browser_origin"]["immutable_asset_prefixes"] = value
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, "immutable_asset_prefixes"):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_unsafe_sandboxed_frame_resource_prefixes(self) -> None:
        invalid_values = (
            ["/"],
            ["api/plugins/"],
            ["/api/"],
            ["/.well-known/"],
            ["/api/plugins//"],
            ["/api/%2e%2e/"],
            ["/api/plugins/{id}"],
            ["/api/plugins/", "/api/plugins/"],
            [f"/asset-{index}" for index in range(9)],
        )
        for value in invalid_values:
            with self.subTest(value=value), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                payload["services"]["http_sidecars"][0]["browser_origin"][
                    "sandboxed_frame_resource_prefixes"
                ] = value
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, "sandboxed_frame_resource_prefixes"):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_non_loopback_sandbox_sidecar(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["services"]["http_sidecars"][0]["bind"]["host"] = "0.0.0.0"
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "loopback"):
                parse_app_contract_file(app_root)

    def test_entrypoint_access_is_bounded_separate_and_read_only_for_reference(self) -> None:
        mutations = (
            (lambda access: access.pop("request_budget"), "request_budget.*required"),
            (lambda access: access.pop("streaming"), "streaming.*required"),
            (lambda access: access.__setitem__("ttl_seconds", 31), "ttl_seconds"),
            (lambda access: access.__setitem__("streaming", True), "distinct job capability"),
            (
                lambda access: access["surfaces"][3]["routes"].__setitem__(
                    0,
                    {"method": "POST", "path_template": "/api/projects"},
                ),
                "only GET or HEAD",
            ),
            (
                lambda access: access["surfaces"][0]["routes"].__setitem__(
                    0,
                    {"method": "GET", "path_template": "/api/projects/{id}/files"},
                ),
                "exact subset",
            ),
            (
                lambda access: access["surfaces"].append(dict(access["surfaces"][0])),
                "Duplicate entrypoint access surface",
            ),
        )
        for mutate, expected in mutations:
            with self.subTest(expected=expected), TemporaryDirectory() as temp_dir:
                app_root = self._write_sidecar_app(Path(temp_dir))
                payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
                mutate(payload["services"]["http_sidecars"][0]["entrypoint_access"])
                (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(AppContractValidationError, expected):
                    parse_app_contract_file(app_root)

    def test_parse_contract_rejects_sidecar_logs_outside_workspace_log_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["services"]["http_sidecars"][0]["logs"]["stdout"] = "data/sidecar-demo/sidecar.log"
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "logs/apps/sidecar-demo"):
                parse_app_contract_file(app_root)
