"""Synthetic fixtures shared by isolated publication and HTTP tests."""
import base64
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import sys
import time
import zipfile

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))
sys.path.insert(0, str(APP_ROOT))

from external_apps.context import Context
from external_apps.service import Service


def context(workspace="tenant-a", **changes):
    return replace(Context(workspace, "user-admin", "admin", "", "backend", "", "selected-exporter"), **changes)


def success_probe(*_args):
    return {"status": "healthy", "checked_at": time.time()}


def service(root, *, workspace="tenant-a", probe=success_probe):
    result = Service(root, context(workspace), probe=probe, preflight=lambda _host: None)
    result.handle({"action": "deployment.configure", "installation_domain": "example.test"})
    return result


def prepare(service, *, app_id=None, content="one", format_="static_bundle"):
    body = {"action": "publish.plan", "source_entity_id": "site_synthetic", "build_id": "build_synthetic", "name": "Synthetic", "format": format_}
    if app_id:
        body["external_app_id"] = app_id
    initial = service.handle(body)
    plan = initial["plan"]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("index.html", '<!doctype html><html><head><base href="/_releases/' + plan["release_id"] + '/"></head><body>' + content + '</body></html>')
        archive.writestr("main.js", 'window.synthetic="' + content + '";')
    data = stream.getvalue()
    exported = {"schema_version": "external-static-export.v1", "entity_type": "site", "entity_id": "site_synthetic",
                "source_revision": "revision-" + content, "release_id": plan["release_id"], "format": format_, "entrypoint": "index.html",
                "artifact": {"transport": "base64", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                             "content_base64": base64.b64encode(data).decode()}}
    callback = {"action": "export.completed", "plan_id": plan["id"], "request_id": plan["id"],
                "dependency_alias": "static-exporter", "request": initial["dependency_backend_requests"][0],
                "dependency_backend_status": "completed", "dependency_backend_result": {
                    "dependency_provider_app_id": service.ctx.provider_id, "status_code": 200, "json": exported}}
    worker = Service(service.root, replace(service.ctx, surface="dependency_backend_request_callback"))
    return worker.handle(callback)["plan"]


def approve(service, plan):
    return service.handle({"action": "plan.approve", "plan_id": plan["id"], "plan_digest": plan["plan_digest"], "confirm": True})["plan"]


def apply_args(plan, key="publish-idempotency-1"):
    return {"action": plan["kind"] + ".apply", "plan_id": plan["id"], "plan_digest": plan["plan_digest"],
            "confirm": True, "idempotency_key": key}
