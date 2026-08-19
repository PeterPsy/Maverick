"""Store adapters for app-hosting control-plane records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Protocol

from core.apps.errors import (
    AppSourceNotFoundError,
    WorkspaceAppBindingNotFoundError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.models import (
    AppCapabilities,
    AppContractDescriptor,
    AppDataEventDeclaration,
    AppDistributionDeclaration,
    AppEntrypoints,
    AppFailureSemantics,
    AppHealthContract,
    AppHostPermissionDeclaration,
    AppHookTimeouts,
    AppLifecycleDeclaration,
    AppCompatibilityDescriptor,
    AppNetworkPermissionDeclaration,
    AppPermissionsDeclaration,
    AppPresentationDeclaration,
    AppProviderPermissionDeclaration,
    AppProvidedInterfaceDeclaration,
    AppReferenceEntityDeclaration,
    AppRequiredInterfaceDeclaration,
    AppRollbackSupport,
    AppRuntimePermissionDeclaration,
    AppSecretPermissionDeclaration,
    AppServicesDeclaration,
    AppSourceRecord,
    AppStorageDeclaration,
    AppStorageIndices,
    AppViewStateActionDeclaration,
    AppViewSurfaceDeclaration,
    AppVisibilityDeclaration,
    HttpSidecarBindSpec,
    HttpSidecarBrowserOriginSpec,
    HttpSidecarEntrypointAccessSpec,
    HttpSidecarEntrypointSurfaceSpec,
    HttpSidecarHealthSpec,
    HttpSidecarLogSpec,
    HttpSidecarProcessPolicy,
    HttpSidecarProxySpec,
    HttpSidecarResourceLimits,
    HttpSidecarRoutePolicy,
    HttpSidecarRouteRule,
    HttpSidecarSpec,
    WidgetActionDeclaration,
    WidgetDeclaration,
    WidgetFrontendDeclaration,
    WorkspaceAppBindingRecord,
    WorkspaceAppDependencySelectionRecord,
    WorkspaceLocalAppProjectRecord,
)


class DocumentCollection(Protocol):
    """Minimal collection protocol used by control-plane stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


class AppStore(Protocol):
    """Persistence contract for app-hosting control-plane records."""

    def save_app_source(self, record: AppSourceRecord) -> AppSourceRecord:
        ...

    def get_app_source(self, source_id: str) -> AppSourceRecord:
        ...

    def list_app_sources(self) -> list[AppSourceRecord]:
        ...

    def save_workspace_local_app_project(self, record: WorkspaceLocalAppProjectRecord) -> WorkspaceLocalAppProjectRecord:
        ...

    def get_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> WorkspaceLocalAppProjectRecord:
        ...

    def list_workspace_local_app_projects(self, workspace_id: str) -> list[WorkspaceLocalAppProjectRecord]:
        ...

    def delete_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> None:
        ...

    def save_workspace_app_binding(self, record: WorkspaceAppBindingRecord) -> WorkspaceAppBindingRecord:
        ...

    def get_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> WorkspaceAppBindingRecord:
        ...

    def list_workspace_app_bindings(self, workspace_id: str) -> list[WorkspaceAppBindingRecord]:
        ...

    def delete_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> None:
        ...

    def save_workspace_app_dependency_selection(
        self,
        record: WorkspaceAppDependencySelectionRecord,
    ) -> WorkspaceAppDependencySelectionRecord:
        ...

    def get_workspace_app_dependency_selection(
        self,
        *,
        workspace_id: str,
        consumer_app_id: str,
        alias: str,
    ) -> WorkspaceAppDependencySelectionRecord | None:
        ...

    def list_workspace_app_dependency_selections(
        self,
        *,
        workspace_id: str,
        consumer_app_id: str | None = None,
    ) -> list[WorkspaceAppDependencySelectionRecord]:
        ...

    def delete_workspace_app_dependency_selection(
        self,
        *,
        workspace_id: str,
        consumer_app_id: str,
        alias: str,
    ) -> None:
        ...


@dataclass(frozen=True)
class AppCollections:
    """Collection bundle for app-hosting control-plane persistence."""

    app_sources: DocumentCollection
    workspace_local_app_projects: DocumentCollection
    workspace_app_bindings: DocumentCollection
    workspace_app_dependency_selections: DocumentCollection


class AppDocumentStore:
    """Persist app-hosting control-plane records in document collections."""

    def __init__(self, collections: AppCollections) -> None:
        self.collections = collections

    def _app_contract(self, payload: dict[str, Any]) -> AppContractDescriptor:
        capabilities_payload = dict(payload["capabilities"])
        capabilities_payload["reference_entities"] = [
            AppReferenceEntityDeclaration(**entity)
            for entity in capabilities_payload.get("reference_entities", [])
        ]
        capabilities_payload["data_events"] = [
            AppDataEventDeclaration(**event)
            for event in capabilities_payload.get("data_events", [])
        ]
        capabilities_payload["view_surfaces"] = [
            AppViewSurfaceDeclaration(
                **{
                    **surface,
                    "state_actions": [
                        AppViewStateActionDeclaration(**action)
                        for action in surface.get("state_actions", [])
                    ],
                }
            )
            for surface in capabilities_payload.get("view_surfaces", [])
        ]
        return AppContractDescriptor(
            provides=[
                AppProvidedInterfaceDeclaration(**item)
                for item in payload.get("provides", [])
            ],
            requires=[
                AppRequiredInterfaceDeclaration(**item)
                for item in payload.get("requires", [])
            ],
            distribution=AppDistributionDeclaration(**payload["distribution"]),
            visibility=AppVisibilityDeclaration(**payload.get("visibility", {"platform_roles": None})),
            presentation=AppPresentationDeclaration(**payload["presentation"]),
            permissions=AppPermissionsDeclaration(
                secrets=AppSecretPermissionDeclaration(
                    **payload.get("permissions", {}).get("secrets", {"read": [], "write": []})
                ),
                network=AppNetworkPermissionDeclaration(
                    **payload.get("permissions", {}).get("network", {"outbound": []})
                ),
                runtime=AppRuntimePermissionDeclaration(
                    **payload.get("permissions", {}).get(
                        "runtime",
                        {
                            "create_sessions": False,
                            "cleanup_sessions": False,
                            "receive_cleanup_callbacks": False,
                        },
                    )
                ),
                host=AppHostPermissionDeclaration(
                    **payload.get("permissions", {}).get("host", {"telemetry": False})
                ),
                providers=AppProviderPermissionDeclaration(
                    **payload.get("permissions", {}).get(
                        "providers",
                        {
                            "model_proxy": False,
                            "credential_source": "none",
                            "deliver_secrets_to_app": False,
                        },
                    )
                ),
            ),
            compatibility=AppCompatibilityDescriptor(**payload["compatibility"]),
            storage=AppStorageDeclaration(
                **{
                    **payload["storage"],
                    "indices": (
                        AppStorageIndices(**payload["storage"]["indices"])
                        if payload["storage"].get("indices") is not None
                        else None
                    ),
                }
            ),
            capabilities=AppCapabilities(**capabilities_payload),
            lifecycle=AppLifecycleDeclaration(**_known_dataclass_values(AppLifecycleDeclaration, payload["lifecycle"])),
            entrypoints=AppEntrypoints(**payload["entrypoints"]),
            hook_timeouts=AppHookTimeouts(**{"backend_seconds": 30, **payload["hook_timeouts"]}),
            failure_semantics=AppFailureSemantics(**payload["failure_semantics"]),
            health_contract=AppHealthContract(**payload["health_contract"]),
            rollback_support=AppRollbackSupport(**payload["rollback_support"]),
            widgets=[
                WidgetDeclaration(
                    widget_id=widget["widget_id"],
                    host=widget["host"],
                    content_kinds=list(widget["content_kinds"]),
                    frontend=WidgetFrontendDeclaration(**widget["frontend"]),
                    actions=WidgetActionDeclaration(**widget["actions"]),
                )
                for widget in payload.get("widgets", [])
            ],
            services=_app_services(payload.get("services", {})),
        )

    def _app_source_record(self, document: dict[str, Any]) -> AppSourceRecord:
        payload = dict(document)
        payload["contract"] = self._app_contract(payload["contract"])
        payload.setdefault("public_app_id", payload.get("app_id"))
        return AppSourceRecord(**payload)

    def _workspace_local_project_record(self, document: dict[str, Any]) -> WorkspaceLocalAppProjectRecord:
        payload = dict(document)
        payload["contract"] = self._app_contract(payload["contract"])
        payload.setdefault("public_app_id", payload.get("app_id"))
        payload.setdefault("local_app_id", payload.get("app_id"))
        return WorkspaceLocalAppProjectRecord(**payload)

    def _workspace_app_binding_record(self, document: dict[str, Any]) -> WorkspaceAppBindingRecord:
        payload = dict(document)
        payload.setdefault("public_app_id", payload.get("app_id"))
        payload.setdefault("local_app_id", payload.get("app_id"))
        payload.setdefault("mount_app_id", payload.get("app_id"))
        return WorkspaceAppBindingRecord(**payload)

    def save_app_source(self, record: AppSourceRecord) -> AppSourceRecord:
        self.collections.app_sources.update_one(
            {"source_id": record.source_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_app_source(self, source_id: str) -> AppSourceRecord:
        document = self.collections.app_sources.find_one({"source_id": source_id})
        if document is None:
            raise AppSourceNotFoundError(f"App source `{source_id}` was not found.")
        return self._app_source_record(document)

    def list_app_sources(self) -> list[AppSourceRecord]:
        return [self._app_source_record(document) for document in self.collections.app_sources.find({})]

    def save_workspace_local_app_project(self, record: WorkspaceLocalAppProjectRecord) -> WorkspaceLocalAppProjectRecord:
        self.collections.workspace_local_app_projects.update_one(
            {"workspace_id": record.workspace_id, "app_id": record.app_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> WorkspaceLocalAppProjectRecord:
        document = self.collections.workspace_local_app_projects.find_one(
            {"workspace_id": workspace_id, "app_id": app_id}
        )
        if document is None:
            raise WorkspaceLocalAppProjectNotFoundError(
                f"Workspace-local app project `{app_id}` was not found in workspace `{workspace_id}`."
            )
        return self._workspace_local_project_record(document)

    def list_workspace_local_app_projects(self, workspace_id: str) -> list[WorkspaceLocalAppProjectRecord]:
        return [
            self._workspace_local_project_record(document)
            for document in self.collections.workspace_local_app_projects.find({"workspace_id": workspace_id})
        ]

    def delete_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> None:
        self.collections.workspace_local_app_projects.delete_one({"workspace_id": workspace_id, "app_id": app_id})

    def save_workspace_app_binding(self, record: WorkspaceAppBindingRecord) -> WorkspaceAppBindingRecord:
        self.collections.workspace_app_bindings.update_one(
            {"workspace_id": record.workspace_id, "app_id": record.app_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> WorkspaceAppBindingRecord:
        document = self.collections.workspace_app_bindings.find_one({"workspace_id": workspace_id, "app_id": app_id})
        if document is None:
            raise WorkspaceAppBindingNotFoundError(
                f"Workspace app binding `{app_id}` was not found in workspace `{workspace_id}`."
            )
        return self._workspace_app_binding_record(document)

    def list_workspace_app_bindings(self, workspace_id: str) -> list[WorkspaceAppBindingRecord]:
        return [
            self._workspace_app_binding_record(document)
            for document in self.collections.workspace_app_bindings.find({"workspace_id": workspace_id})
        ]

    def delete_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> None:
        self.collections.workspace_app_bindings.delete_one({"workspace_id": workspace_id, "app_id": app_id})

    def save_workspace_app_dependency_selection(
        self,
        record: WorkspaceAppDependencySelectionRecord,
    ) -> WorkspaceAppDependencySelectionRecord:
        self.collections.workspace_app_dependency_selections.update_one(
            {"workspace_id": record.workspace_id, "consumer_app_id": record.consumer_app_id, "alias": record.alias},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_workspace_app_dependency_selection(
        self,
        *,
        workspace_id: str,
        consumer_app_id: str,
        alias: str,
    ) -> WorkspaceAppDependencySelectionRecord | None:
        document = self.collections.workspace_app_dependency_selections.find_one(
            {"workspace_id": workspace_id, "consumer_app_id": consumer_app_id, "alias": alias}
        )
        if document is None:
            return None
        return WorkspaceAppDependencySelectionRecord(**document)

    def list_workspace_app_dependency_selections(
        self,
        *,
        workspace_id: str,
        consumer_app_id: str | None = None,
    ) -> list[WorkspaceAppDependencySelectionRecord]:
        query: dict[str, str] = {"workspace_id": workspace_id}
        if consumer_app_id is not None:
            query["consumer_app_id"] = consumer_app_id
        return [
            WorkspaceAppDependencySelectionRecord(**document)
            for document in self.collections.workspace_app_dependency_selections.find(query)
        ]

    def delete_workspace_app_dependency_selection(
        self,
        *,
        workspace_id: str,
        consumer_app_id: str,
        alias: str,
    ) -> None:
        self.collections.workspace_app_dependency_selections.delete_one(
            {"workspace_id": workspace_id, "consumer_app_id": consumer_app_id, "alias": alias}
        )


def _known_dataclass_values(model: type[Any], payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {field.name for field in fields(model)}
    return {key: value for key, value in payload.items() if key in allowed}


def _app_services(payload: Any) -> AppServicesDeclaration:
    if not isinstance(payload, dict):
        return AppServicesDeclaration(http_sidecars=[])
    return AppServicesDeclaration(
        http_sidecars=[
            HttpSidecarSpec(
                service_id=str(sidecar.get("id") or sidecar.get("service_id")),
                runtime=sidecar["runtime"],
                package_manager=sidecar.get("package_manager"),
                working_directory=sidecar["working_directory"],
                command=list(sidecar["command"]),
                env={str(key): str(value) for key, value in sidecar.get("env", {}).items()},
                process_policy=_app_sidecar_process_policy(sidecar.get("process_policy")),
                browser_origin=_app_sidecar_browser_origin(sidecar.get("browser_origin")),
                entrypoint_access=_app_sidecar_entrypoint_access(
                    sidecar.get("entrypoint_access"),
                    proxy_payload=sidecar.get("proxy"),
                ),
                bind=HttpSidecarBindSpec(**sidecar["bind"]),
                health=HttpSidecarHealthSpec(**sidecar["health"]),
                proxy=_app_sidecar_proxy(sidecar.get("proxy")),
                logs=(HttpSidecarLogSpec(**sidecar["logs"]) if sidecar.get("logs") is not None else None),
            )
            for sidecar in payload.get("http_sidecars", [])
        ]
    )


def _app_sidecar_process_policy(payload: Any) -> HttpSidecarProcessPolicy:
    if not isinstance(payload, dict):
        payload = {}
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    return HttpSidecarProcessPolicy(
        inherit_host_env=False,
        sandbox="required",
        bundle_read_only=True,
        workspace_data_write=True,
        network="isolated",
        transport="unix_relay",
        outbound=[],
        limits=HttpSidecarResourceLimits(
            memory_bytes=int(limits.get("memory_bytes", 4 * 1024 * 1024 * 1024)),
            open_files=int(limits.get("open_files", 1024)),
            request_concurrency=int(limits.get("request_concurrency", 32)),
        ),
    )


def _app_sidecar_browser_origin(payload: Any) -> HttpSidecarBrowserOriginSpec | None:
    if not isinstance(payload, dict):
        return None
    return HttpSidecarBrowserOriginSpec(
        mode="isolated",
        csp_profile="self_hosted_web_app",
        frame_ancestors=["platform"],
        connect_src=["self"],
    )


def _app_sidecar_entrypoint_access(
    payload: Any,
    *,
    proxy_payload: Any,
) -> HttpSidecarEntrypointAccessSpec | None:
    if not isinstance(payload, dict):
        return None
    ttl_seconds = payload.get("ttl_seconds")
    request_budget = payload.get("request_budget")
    max_request_body_bytes = payload.get("max_request_body_bytes")
    max_response_body_bytes = payload.get("max_response_body_bytes")
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or not 1 <= ttl_seconds <= 30
        or isinstance(request_budget, bool)
        or not isinstance(request_budget, int)
        or not 1 <= request_budget <= 256
        or isinstance(max_request_body_bytes, bool)
        or not isinstance(max_request_body_bytes, int)
        or not 0 <= max_request_body_bytes <= 16 * 1024 * 1024
        or isinstance(max_response_body_bytes, bool)
        or not isinstance(max_response_body_bytes, int)
        or not 1 <= max_response_body_bytes <= 64 * 1024 * 1024
        or payload.get("streaming") is not False
    ):
        return None
    raw_surfaces = payload.get("surfaces")
    if not isinstance(raw_surfaces, list) or not raw_surfaces:
        return None
    raw_pass_through = (
        proxy_payload.get("route_policy", {}).get("pass_through", [])
        if isinstance(proxy_payload, dict)
        else []
    )
    pass_through = {
        (
            route.get("method"),
            route.get("path_template"),
            bool(route.get("static_tree", False)),
        )
        for route in raw_pass_through
        if isinstance(route, dict)
    }
    surfaces: list[HttpSidecarEntrypointSurfaceSpec] = []
    seen_surfaces: set[str] = set()
    for raw_surface in raw_surfaces:
        if not isinstance(raw_surface, dict) or raw_surface.get("surface") not in {
            "backend",
            "cli",
            "mcp",
            "reference",
        }:
            return None
        if raw_surface["surface"] in seen_surfaces:
            return None
        seen_surfaces.add(raw_surface["surface"])
        routes = _app_sidecar_route_rules(raw_surface.get("routes"))
        if (
            not routes
            or any(route.method is None or route.static_tree for route in routes)
            or raw_surface["surface"] == "reference"
            and any(route.method not in {"GET", "HEAD"} for route in routes)
            or any((route.method, route.path_template, route.static_tree) not in pass_through for route in routes)
        ):
            return None
        surfaces.append(
            HttpSidecarEntrypointSurfaceSpec(
                surface=raw_surface["surface"],
                routes=routes,
            )
        )
    return HttpSidecarEntrypointAccessSpec(
        ttl_seconds=ttl_seconds,
        request_budget=request_budget,
        max_request_body_bytes=max_request_body_bytes,
        max_response_body_bytes=max_response_body_bytes,
        streaming=False,
        surfaces=surfaces,
    )


def _app_sidecar_proxy(payload: Any) -> HttpSidecarProxySpec | None:
    if not isinstance(payload, dict):
        return None
    route_policy = payload["route_policy"]
    return HttpSidecarProxySpec(
        mount=payload["mount"],
        streaming=payload["streaming"],
        sse=payload["sse"],
        websocket=payload["websocket"],
        route_policy=HttpSidecarRoutePolicy(
            pass_through=_app_sidecar_route_rules(route_policy.get("pass_through", [])),
            handled_by_core=_app_sidecar_route_rules(route_policy.get("handled_by_core", [])),
            blocked=_app_sidecar_route_rules(route_policy.get("blocked", [])),
        ),
    )


def _app_sidecar_route_rules(payload: Any) -> list[HttpSidecarRouteRule]:
    if not isinstance(payload, list):
        return []
    rules: list[HttpSidecarRouteRule] = []
    for rule in payload:
        if not isinstance(rule, dict) or not isinstance(rule.get("path_template"), str):
            continue
        rules.append(
            HttpSidecarRouteRule(
                method=rule.get("method"),
                path_template=rule["path_template"],
                static_tree=bool(rule.get("static_tree", False)),
            )
        )
    return rules
