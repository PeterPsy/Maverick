"""App contract tests for app-owned HTTP sidecar services."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contract_serializer import app_contract_payload
from core.apps.contracts import (
    build_app_contract,
    build_app_services,
    build_http_sidecar_browser_origin,
    build_http_sidecar_entrypoint_access,
    build_http_sidecar_entrypoint_surface,
    build_http_sidecar_logs,
    build_http_sidecar_process_policy,
    build_http_sidecar_proxy,
    build_http_sidecar_route_policy,
    build_http_sidecar_route_rule,
    build_http_sidecar_spec,
    build_parsed_app_contract,
    parse_app_contract_file,
    write_app_contract_file,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import HttpSidecarBindSpec, HttpSidecarHealthSpec


class AppContractServiceTests(unittest.TestCase):
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
            self.assertEqual(loaded.contract.services.http_sidecars[0].browser_origin.mode, "isolated")
            self.assertEqual(loaded.contract.services.http_sidecars[0].browser_origin.frame_ancestors, ["platform"])
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
            ({"method": "POST", "path_template": "/api/projects/{*path}"}, "one segment"),
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
            ("MAVERICK_BOOTSTRAP_SECRET", "bootstrap-secret"),
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

    def _write_sidecar_app(self, root: Path) -> Path:
        app_root = root / "apps" / "sidecar-demo"
        (app_root / "service").mkdir(parents=True)
        parsed = build_parsed_app_contract(
            app_id="sidecar-demo",
            name="Sidecar Demo",
            version="0.1.0",
            description="HTTP sidecar test app.",
            publisher="maverick",
            contract=build_app_contract(
                services=build_app_services(
                    http_sidecars=[
                        build_http_sidecar_spec(
                            service_id="opendesign",
                            runtime="python",
                            working_directory="service",
                            command=["python3", "server.py"],
                            env={
                                "OD_BIND_HOST": "127.0.0.1",
                                "OD_PORT": "${service.port}",
                                "OD_API_TOKEN": "${service.token}",
                            },
                            process_policy=build_http_sidecar_process_policy(
                                memory_bytes=2 * 1024 * 1024 * 1024,
                                open_files=512,
                                request_concurrency=16,
                            ),
                            browser_origin=build_http_sidecar_browser_origin(),
                            entrypoint_access=build_http_sidecar_entrypoint_access(
                                ttl_seconds=30,
                                request_budget=8,
                                max_request_body_bytes=4096,
                                max_response_body_bytes=65536,
                                streaming=False,
                                surfaces=[
                                    build_http_sidecar_entrypoint_surface(
                                        surface="backend",
                                        routes=[
                                            build_http_sidecar_route_rule(
                                                method="GET",
                                                path_template="/api/projects",
                                            )
                                        ],
                                    ),
                                    build_http_sidecar_entrypoint_surface(
                                        surface="cli",
                                        routes=[
                                            build_http_sidecar_route_rule(
                                                method="POST",
                                                path_template="/api/projects",
                                            )
                                        ],
                                    ),
                                    build_http_sidecar_entrypoint_surface(
                                        surface="mcp",
                                        routes=[
                                            build_http_sidecar_route_rule(
                                                method="GET",
                                                path_template="/api/projects/{id}",
                                            )
                                        ],
                                    ),
                                    build_http_sidecar_entrypoint_surface(
                                        surface="reference",
                                        routes=[
                                            build_http_sidecar_route_rule(
                                                method="GET",
                                                path_template="/api/projects/{id}",
                                            )
                                        ],
                                    ),
                                ],
                            ),
                            bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
                            health=HttpSidecarHealthSpec(path="/api/ready", timeout_ms=5000),
                            proxy=build_http_sidecar_proxy(
                                mount="/opendesign",
                                streaming=False,
                                sse=False,
                                route_policy=build_http_sidecar_route_policy(
                                    pass_through=[
                                        build_http_sidecar_route_rule(method="GET", path_template="/"),
                                        build_http_sidecar_route_rule(method="GET", path_template="/api/projects"),
                                        build_http_sidecar_route_rule(method="POST", path_template="/api/projects"),
                                        build_http_sidecar_route_rule(method="GET", path_template="/api/projects/{id}"),
                                    ],
                                    handled_by_core=[
                                        build_http_sidecar_route_rule(
                                            method="POST",
                                            path_template="/api/provider/{operation}",
                                        ),
                                    ],
                                    blocked=[
                                        build_http_sidecar_route_rule(path_template="/api/import/folder"),
                                    ],
                                ),
                            ),
                            logs=build_http_sidecar_logs(
                                stdout="logs/apps/sidecar-demo/sidecar.log",
                                stderr="logs/apps/sidecar-demo/sidecar.log",
                            ),
                        )
                    ]
                )
            ),
        )
        write_app_contract_file(app_root, parsed)
        (app_root / "service" / "server.py").write_text("print('ready')\n", encoding="utf-8")
        return app_root
