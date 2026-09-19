"""One product service for backend, CLI and MCP; public runtime is independent."""
from pathlib import Path
import time

from . import deployment, operations, plans
from .bindings import read_binding
from .errors import AppError
from .files import publication_lock
from .maintenance import capacity, cleanup
from .probe import verify_https
from .store import Store

READS = {"operations.manifest", "list", "get", "health"}
MUTATIONS = {"publish.plan", "publish.apply", "rollback.plan", "rollback.apply", "suspend", "archive", "deployment.configure"}
ACTIONS = READS | MUTATIONS


class Service:
    def __init__(self, root: Path, ctx, *, probe=verify_https):
        if not root.is_absolute() or not ctx.workspace_id:
            raise AppError("workspace_context_required", 403)
        self.root, self.ctx, self.probe = root, ctx, probe
        self.store = Store(root, ctx.workspace_id)
        self.store.assert_workspace()

    def handle(self, body):
        action = body.get("action", "operations.manifest")
        if action == "export.completed":
            with publication_lock(self.root):
                return plans.complete_export(self.store, self.ctx, body)
        self.ctx.require_user(admin=action not in READS)
        if action not in ACTIONS | {"plan.approve"}:
            raise AppError("unsupported_action")
        if action == "operations.manifest":
            return {"actions": sorted(ACTIONS), "approval": "authenticated_ui_only", "publish_format": "zip.v1",
                    "hosted_mutation_policy": "core_admission_required_otherwise_use_ui"}
        if action == "health":
            try:
                config = deployment.load(self.root)
                return {"status": "configured", "domain": config["domain"], "public_verification": "per_release"}
            except AppError as error:
                return {"status": "not_configured", "error_code": error.code}
        if action == "list":
            offset = body.get("offset", 0)
            limit = body.get("limit", 50)
            if type(offset) is not int or type(limit) is not int or not 1 <= limit <= 100:
                raise AppError("invalid_pagination")
            # Catalog cap is 100; filter before pagination to avoid sparse pages.
            items = [self.describe(app) for app in self.store.list("apps", limit=100)]
            query = str(body.get("query", "")).casefold()[:120]
            status = body.get("status", "")
            items = [app for app in items if (not query or query in app["name"].casefold())
                     and (not status or app["status"] == status)
                     and (status == "archived" or app["status"] != "archived")]
            return {"items": items[offset:offset + limit], "total": len(items), "next_offset": offset + limit if len(items) > offset + limit else None}
        if action == "get":
            if body.get("plan_id"):
                return {"plan": self.store.get("plans", body["plan_id"])}
            app = self.store.get("apps", body.get("external_app_id"))
            return {"app": self.describe(app), "plans": self.store.list("plans", app_id=app["id"], limit=20),
                    "releases": self.store.list("releases", app_id=app["id"], limit=30), "history": self.store.history(app["id"])}
        with publication_lock(self.root):
            self.store.initialize()
        if action in {"publish.apply", "rollback.apply"}:
            config = deployment.load(self.root)
            plan = self.store.get("plans", body.get("plan_id"))
            if not plan["hostname"].endswith("." + config["domain"]):
                raise AppError("deployment_changed", 409)
            return operations.apply(self.store, self.ctx, body, self.probe)
        if action in {"suspend", "archive"}:
            return operations.disable(self.store, self.ctx, body)
        with publication_lock(self.root):
            operations.recover(self.store)
            if action == "deployment.configure":
                config = deployment.configure(self.root, body.get("domain"), has_apps=bool(self.store.list("apps", limit=1)))
                self.store.audit("", "deployment.configured", self.ctx.user_id)
                return {"deployment": config}
            if action == "publish.plan":
                cleanup(self.store)
                capacity(self.store)
                return plans.prepare(self.store, self.ctx, deployment.load(self.root), body)
            if action == "rollback.plan":
                cleanup(self.store)
                capacity(self.store)
                return plans.rollback_plan(self.store, self.ctx, self.store.get("apps", body.get("external_app_id")))
            if action == "plan.approve":
                return plans.approve(self.store, self.ctx, body)
        raise AppError("unsupported_action")

    def describe(self, app):
        binding = read_binding(self.root / "public", app["public_id"])
        status = "archived" if binding["archived"] else ("published" if binding["enabled"] else ("suspended" if binding["generation"] else "draft"))
        health = {"status": "unknown"}
        last_error = ""
        for operation in self.store.list("operations", app_id=app["id"], limit=10):
            result = operation.get("result") or {}
            if not last_error:
                last_error = result.get("error_code", "")
            if result.get("release_id") == (binding.get("current") or {}).get("release_id") and result.get("health"):
                health = dict(result["health"])
                if health.get("checked_at", 0) < time.time() - 300:
                    health["status"] = "unknown"
                break
        return {**app, "status": status, "binding": binding, "health": health,
                "last_error_code": last_error, "managed_url": "https://" + app["hostname"]}
