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
    build_http_sidecar_logs,
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
            self.assertEqual(loaded.contract.services.http_sidecars[0].proxy.route_policy.blocked[0].path_prefix, "/api/import/folder")
            self.assertEqual(json.loads((app_root / "app_contract.json").read_text(encoding="utf-8")), payload)

    def test_parse_contract_rejects_exposed_sidecar_without_route_policy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            del payload["services"]["http_sidecars"][0]["proxy"]["route_policy"]
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "route_policy"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_non_loopback_sandbox_sidecar(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["services"]["http_sidecars"][0]["bind"]["host"] = "0.0.0.0"
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "loopback"):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_sidecar_logs_outside_workspace_log_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = self._write_sidecar_app(Path(temp_dir))
            payload = json.loads((app_root / "app_contract.json").read_text(encoding="utf-8"))
            payload["services"]["http_sidecars"][0]["logs"]["stdout"] = "data/design-studio/sidecar.log"
            (app_root / "app_contract.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(AppContractValidationError, "logs/apps/design-studio"):
                parse_app_contract_file(app_root)

    def _write_sidecar_app(self, root: Path) -> Path:
        app_root = root / "apps" / "design-studio"
        (app_root / "service").mkdir(parents=True)
        parsed = build_parsed_app_contract(
            app_id="design-studio",
            name="Design Studio",
            version="0.1.0",
            description="OpenDesign sidecar test app.",
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
                                "OD_API_TOKEN": "${service_secret:od_api_token}",
                            },
                            bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
                            health=HttpSidecarHealthSpec(path="/api/ready", timeout_ms=5000),
                            proxy=build_http_sidecar_proxy(
                                mount="/opendesign",
                                streaming=False,
                                sse=False,
                                route_policy=build_http_sidecar_route_policy(
                                    pass_through=[
                                        build_http_sidecar_route_rule(method="GET", path_prefix="/"),
                                        build_http_sidecar_route_rule(method="POST", path_prefix="/api/projects"),
                                    ],
                                    handled_by_core=[
                                        build_http_sidecar_route_rule(path_prefix="/api/provider"),
                                    ],
                                    blocked=[
                                        build_http_sidecar_route_rule(path_prefix="/api/import/folder"),
                                    ],
                                ),
                            ),
                            logs=build_http_sidecar_logs(
                                stdout="logs/apps/design-studio/sidecar.log",
                                stderr="logs/apps/design-studio/sidecar.log",
                            ),
                        )
                    ]
                )
            ),
        )
        write_app_contract_file(app_root, parsed)
        (app_root / "service" / "server.py").write_text("print('ready')\n", encoding="utf-8")
        return app_root
