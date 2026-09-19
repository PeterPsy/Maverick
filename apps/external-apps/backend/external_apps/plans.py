"""Prepare immutable publication plans and verify official export callbacks."""
import base64
import binascii
import hashlib
import time
from uuid import uuid4

from .artifacts import promote
from .bindings import read_binding
from .errors import AppError
from .files import encoded
from .policy import MAX_APPS, MAX_RELEASES, MAX_ZIP, PLAN_TTL, slug


def plan_digest(plan):
    keys = ("id", "app_id", "kind", "provider_id", "source_id", "source_revision", "release",
            "hostname", "expected_generation", "created_by", "expires")
    return hashlib.sha256(encoded({k: plan.get(k) for k in keys})).hexdigest()


def prepare(store, ctx, config, body):
    if not ctx.provider_id:
        raise AppError("exporter_not_selected", 409)
    source_id = str(body.get("source_entity_id") or "")
    build_id = str(body.get("build_id") or "")
    if not source_id or len(source_id) > 128 or not build_id or len(build_id) > 128:
        raise AppError("source_and_build_required")
    format_ = body.get("format", "static_bundle")
    if format_ not in {"static_bundle", "spa_bundle"}:
        raise AppError("unsupported_format")
    now = time.time()
    if body.get("external_app_id"):
        app = store.get("apps", body["external_app_id"])
        if (app["source_id"], app["provider_id"]) != (source_id, ctx.provider_id):
            raise AppError("source_changed", 409)
    else:
        if len(store.list("apps", limit=MAX_APPS)) >= MAX_APPS:
            raise AppError("catalog_capacity_reached", 409)
        public_id = config["namespace"] + uuid4().hex[:20]
        name = str(body.get("name") or "Website").strip()[:120] or "Website"
        app = {"id": "app_" + uuid4().hex, "created": now, "created_by": ctx.user_id,
               "name": name, "public_id": public_id, "slug": slug(name),
               "provider_id": ctx.provider_id, "source_id": source_id}
        app["hostname"] = f"{app['slug']}-{public_id}.{config['domain']}"
        store.put("apps", app, insert=True)
    binding = read_binding(store.root / "public", app["public_id"])
    if binding["archived"]:
        raise AppError("app_archived", 409)
    if len(store.list("releases", limit=MAX_RELEASES)) >= MAX_RELEASES:
        raise AppError("release_capacity_reached", 409)
    plan = {"id": "plan_" + uuid4().hex, "app_id": app["id"], "created": now,
            "created_by": ctx.user_id, "expires": now + PLAN_TTL, "kind": "publish",
            "status": "preparing", "provider_id": ctx.provider_id, "source_id": source_id,
            "build_id": build_id, "hostname": app["hostname"], "format": format_,
            "release_id": "rel_" + uuid4().hex, "expected_generation": binding["generation"],
            "will_replace_release_id": (binding.get("current") or {}).get("release_id"),
            "risk_summary": "All bundle files become public. An opaque URL is not authentication."}
    store.put("plans", plan, insert=True)
    request = {"dependency_alias": "static-exporter", "request_id": plan["id"],
               "body": {"action": "external.static-bundle.export", "schema_version": "external-static-export-request.v1",
                        "entity_type": "site", "entity_id": source_id, "build_id": build_id,
                        "release_id": plan["release_id"], "requested_format": format_},
               "callback": {"action": "export.completed", "payload": {"plan_id": plan["id"]}}}
    store.audit(app["id"], "publish.preparing", ctx.user_id)
    return {"plan": plan, "dependency_backend_requests": [request]}


def complete_export(store, ctx, body):
    if ctx.surface != "dependency_backend_request_callback":
        raise AppError("invalid_callback_surface", 403)
    plan = store.get("plans", body.get("plan_id"))
    if body.get("request_id") != plan["id"] or body.get("dependency_alias") != "static-exporter":
        raise AppError("invalid_dependency_callback", 403)
    original = body.get("request", {})
    if original.get("request_id") != plan["id"] or original.get("body", {}).get("release_id") != plan["release_id"]:
        raise AppError("invalid_dependency_callback", 403)
    if plan["status"] != "preparing":
        return {"plan": plan}  # At-least-once internal callback, no second import.
    try:
        if plan["expires"] < time.time():
            raise AppError("plan_expired", 409)
        result = body.get("dependency_backend_result", {})
        if body.get("dependency_backend_status") != "completed" or result.get("dependency_provider_app_id") != plan["provider_id"]:
            raise AppError("export_failed")
        if result.get("status_code", 500) >= 400:
            raise AppError("export_failed")
        exported = result.get("json", {})
        if (exported.get("schema_version"), exported.get("entity_type"), exported.get("entity_id"), exported.get("release_id"), exported.get("format")) != (
                "external-static-export.v1", "site", plan["source_id"], plan["release_id"], plan["format"]):
            raise AppError("invalid_export")
        artifact = exported.get("artifact", {})
        content = artifact.get("content_base64", "")
        if artifact.get("transport") != "base64" or not isinstance(content, str) or len(content) > ((MAX_ZIP + 2) // 3) * 4:
            raise AppError("artifact_too_large")
        data = base64.b64decode(content, validate=True)
        if artifact.get("size_bytes") != len(data) or artifact.get("sha256") != hashlib.sha256(data).hexdigest():
            raise AppError("artifact_digest_mismatch")
        revision = exported.get("source_revision")
        if not isinstance(revision, str) or not revision or len(revision) > 160:
            raise AppError("invalid_source_revision")
        artifact_info = promote(store.root, data, entrypoint=exported.get("entrypoint", ""))
        release = {"id": plan["release_id"], "release_id": plan["release_id"], "app_id": plan["app_id"],
                   "created": time.time(), "source_revision": revision, "format": plan["format"], **artifact_info}
        store.put("releases", release, insert=True)
        plan.update(status="ready", source_revision=revision, release=release)
        plan["plan_digest"] = plan_digest(plan)
        store.audit(plan["app_id"], "publish.prepared", plan["created_by"])
    except (AppError, binascii.Error, TypeError, KeyError) as error:
        plan.update(status="failed", error_code=error.code if isinstance(error, AppError) else "invalid_export")
    store.put("plans", plan)
    return {"plan": plan}


def rollback_plan(store, ctx, app):
    binding = read_binding(store.root / "public", app["public_id"])
    target = binding.get("previous") or (binding.get("current") if not binding["enabled"] else None)
    if not target or binding["archived"]:
        raise AppError("no_previous_release", 409)
    release = store.get("releases", target["release_id"])
    if release["app_id"] != app["id"]:
        raise AppError("release_owner_mismatch", 403)
    now = time.time()
    plan = {"id": "plan_" + uuid4().hex, "app_id": app["id"], "created": now, "expires": now + PLAN_TTL,
            "created_by": ctx.user_id, "kind": "rollback", "status": "ready", "provider_id": app["provider_id"],
            "source_id": app["source_id"], "source_revision": release["source_revision"], "release": release,
            "hostname": app["hostname"], "expected_generation": binding["generation"],
            "will_replace_release_id": (binding.get("current") or {}).get("release_id"),
            "risk_summary": "Republish the retained release publicly."}
    plan["plan_digest"] = plan_digest(plan)
    store.put("plans", plan, insert=True)
    return {"plan": plan}


def approve(store, ctx, body):
    ctx.require_human()
    plan = store.get("plans", body.get("plan_id"))
    assert_ready(plan, body)
    app = store.get("apps", plan["app_id"])
    if ctx.provider_id != plan["provider_id"]:
        raise AppError("exporter_changed", 409)
    if read_binding(store.root / "public", app["public_id"])["generation"] != plan["expected_generation"]:
        raise AppError("binding_changed", 409)
    plan.update(approved_by=ctx.user_id, approved_at=time.time())
    store.put("plans", plan)
    store.audit(app["id"], "plan.approved", ctx.user_id, plan["plan_digest"])
    return {"plan": plan}


def assert_ready(plan, body):
    if plan["status"] != "ready" or plan["expires"] < time.time():
        raise AppError("plan_not_ready_or_expired", 409)
    if body.get("plan_digest") != plan.get("plan_digest") or plan_digest(plan) != plan.get("plan_digest"):
        raise AppError("plan_digest_mismatch", 409)
    if body.get("confirm") is not True:
        raise AppError("confirmation_required", 403)


def assert_applicable(plan, ctx, body):
    assert_ready(plan, body)
    if body["action"] != plan["kind"] + ".apply":
        raise AppError("plan_kind_mismatch", 409)
    if not plan.get("approved_by"):
        raise AppError("human_ui_confirmation_required", 403)
    if ctx.user_id not in {plan["created_by"], plan["approved_by"]}:
        raise AppError("plan_actor_mismatch", 403)
    if ctx.provider_id != plan["provider_id"]:
        raise AppError("exporter_changed", 409)
