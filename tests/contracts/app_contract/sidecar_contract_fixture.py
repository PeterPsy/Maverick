"""SidecarContractFixture fixtures extracted without changing assertions."""

from __future__ import annotations
from pathlib import Path
from core.apps.contracts import build_app_contract, build_app_services, build_http_sidecar_browser_origin, build_http_sidecar_artifact_mount, build_http_sidecar_root_filesystem, build_http_sidecar_entrypoint_access, build_http_sidecar_entrypoint_surface, build_http_sidecar_logs, build_http_sidecar_process_policy, build_http_sidecar_prewarm, build_http_sidecar_proxy, build_http_sidecar_route_policy, build_http_sidecar_route_rule, build_http_sidecar_spec, build_parsed_app_contract, write_app_contract_file
from core.apps.models import HttpSidecarBindSpec, HttpSidecarHealthSpec


class SidecarContractFixture:
    def _write_sidecar_app(self, root: Path) -> Path:
        app_root = root / "apps" / "sidecar-demo"
        (app_root / "service").mkdir(parents=True)
        parsed = build_parsed_app_contract(
            app_id="sidecar-demo",
            name="Sidecar Demo",
            version="0.1.0",
            description="HTTP sidecar test app.",
            publisher="loopino",
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
                                "OD_ARTIFACT_ROOT": "${artifact.opendesign}",
                            },
                            artifact_mounts=[build_http_sidecar_artifact_mount(artifact_id="opendesign")],
                            root_filesystem=build_http_sidecar_root_filesystem(
                                artifact_id="opendesign",
                                subpath="official/release/rootfs",
                            ),
                            prewarm=build_http_sidecar_prewarm(),
                            process_policy=build_http_sidecar_process_policy(
                                memory_bytes=2 * 1024 * 1024 * 1024,
                                open_files=512,
                                request_concurrency=16,
                            ),
                            browser_origin=build_http_sidecar_browser_origin(
                                immutable_asset_prefixes=["/_next/static/"],
                                sandboxed_frame_resource_prefixes=[
                                    "/api/plugins/",
                                    "/api/asset-cache",
                                ],
                            ),
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
