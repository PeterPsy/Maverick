"""Linearizable binding mutations, conditional compensation and durable retries."""
import hashlib
import time
from uuid import uuid4

from .artifacts import verify
from .bindings import read_binding, write_binding
from .errors import AppError
from .files import encoded, operation_lease, publication_lock
from .plans import assert_applicable


def request_identity(ctx, body):
    key = body.get("idempotency_key")
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise AppError("idempotency_key_required")
    idem = hashlib.sha256(encoded([ctx.workspace_id, ctx.user_id, key])).hexdigest()
    fingerprint = hashlib.sha256(encoded([ctx.workspace_id, ctx.user_id, body])).hexdigest()
    return idem, fingerprint


def _existing(store, idem, fingerprint):
    previous = store.operation(idem)
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise AppError("idempotency_conflict", 409)
        return previous.get("result") or {"status": "in_progress", "operation_id": previous["id"]}
    return None


def recover(store):
    """Caller holds publication lock. Never compensate an operation still running."""
    for operation in store.unfinished():
        with operation_lease(store.root, operation["id"]) as available:
            if not available:
                continue
            actual = read_binding(store.root / "public", operation["public_id"])
            matches = (actual["generation"], actual["operation_id"]) == (
                operation["target"]["generation"], operation["id"])
            if matches and operation["kind"] in {"suspend", "archive"}:
                result = {"status": "suspended" if operation["kind"] == "suspend" else "archived", "generation": actual["generation"], "operation_id": operation["id"]}
            else:
                if matches:
                    restored = {**operation["before"], "generation": actual["generation"] + 1,
                                "operation_id": "recovery_" + uuid4().hex, "updated_at": time.time()}
                    write_binding(store.root, operation["public_id"], restored, expected_generation=actual["generation"])
                result = {"status": "failed", "error_code": "verification_interrupted" if matches else "operation_interrupted",
                          "operation_id": operation["id"]}
            operation["result"] = result
            store.put("operations", operation)
            store.audit(operation["app_id"], "operation.recovered", "system", result["status"])


def apply(store, ctx, body, probe):
    idem, fingerprint = request_identity(ctx, body)
    operation_id = "op_" + uuid4().hex
    with operation_lease(store.root, operation_id):
        with publication_lock(store.root):
            recover(store)
            existing = _existing(store, idem, fingerprint)
            if existing:
                return existing
            plan = store.get("plans", body.get("plan_id"))
            assert_applicable(plan, ctx, body)
            app = store.get("apps", plan["app_id"])
            before = read_binding(store.root / "public", app["public_id"])
            if before["generation"] != plan["expected_generation"] or before["archived"]:
                raise AppError("binding_changed", 409)
            release = plan["release"]
            if release["app_id"] != app["id"]:
                raise AppError("release_owner_mismatch", 403)
            manifest = verify(store.root / "public", release["digest"], release["manifest_digest"])
            public_release = {k: release[k] for k in ("release_id", "digest", "manifest_digest", "format", "entrypoint")}
            target = {**before, "hostname": app["hostname"], "generation": before["generation"] + 1,
                      "enabled": True, "current": public_release, "previous": before.get("current"),
                      "operation_id": operation_id, "updated_at": time.time()}
            operation = {"id": operation_id, "app_id": app["id"], "public_id": app["public_id"],
                         "created": time.time(), "idem": idem, "fingerprint": fingerprint,
                         "kind": plan["kind"], "before": before, "target": target, "result": None}
            store.put("operations", operation, insert=True)
            plan.update(status="applied", operation_id=operation_id)
            store.put("plans", plan)
            write_binding(store.root, app["public_id"], target, expected_generation=before["generation"])
        # No SQLite or publication lock across network I/O. A suspend can win now.
        try:
            health = probe(app["hostname"], release, manifest["files"][release["entrypoint"]]["sha256"])
            error_code = ""
        except AppError as error:
            health = {"status": "degraded", "checked_at": time.time()}
            error_code = error.code
        except Exception:
            health = {"status": "degraded", "checked_at": time.time()}
            error_code = "public_verification_failed"
        with publication_lock(store.root):
            actual = read_binding(store.root / "public", app["public_id"])
            still_ours = (actual["generation"], actual["operation_id"]) == (target["generation"], operation_id)
            if error_code and still_ours:
                restored = {**before, "generation": target["generation"] + 1, "updated_at": time.time(),
                            "operation_id": "compensation_" + uuid4().hex}
                write_binding(store.root, app["public_id"], restored, expected_generation=target["generation"])
                actual = restored
            result = {"status": "failed" if error_code else ("published" if still_ours else "superseded"),
                      "operation_id": operation_id, "release_id": release["release_id"],
                      "managed_url": "https://" + app["hostname"], "generation": actual["generation"], "health": health}
            if error_code:
                result["error_code"] = error_code
            operation["result"] = result
            store.put("operations", operation)
            store.audit(app["id"], plan["kind"] + "." + result["status"], ctx.user_id, error_code)
            return result


def disable(store, ctx, body):
    if body.get("confirm") is not True:
        raise AppError("confirmation_required", 403)
    idem, fingerprint = request_identity(ctx, body)
    with publication_lock(store.root):
        recover(store)
        existing = _existing(store, idem, fingerprint)
        if existing:
            return existing
        app = store.get("apps", body.get("external_app_id"))
        before = read_binding(store.root / "public", app["public_id"])
        if type(body.get("expected_generation")) is not int or body["expected_generation"] != before["generation"]:
            raise AppError("binding_changed", 409)
        operation_id = "op_" + uuid4().hex
        target = {**before, "hostname": app["hostname"], "enabled": False,
                  "archived": before["archived"] or body["action"] == "archive", "generation": before["generation"] + 1,
                  "operation_id": operation_id, "updated_at": time.time()}
        operation = {"id": operation_id, "app_id": app["id"], "public_id": app["public_id"], "created": time.time(),
                     "idem": idem, "fingerprint": fingerprint, "kind": body["action"], "before": before, "target": target, "result": None}
        store.put("operations", operation, insert=True)
        write_binding(store.root, app["public_id"], target, expected_generation=before["generation"])
        result = {"status": "archived" if target["archived"] else "suspended", "generation": target["generation"], "operation_id": operation_id}
        operation["result"] = result
        store.put("operations", operation)
        store.audit(app["id"], body["action"], ctx.user_id)
        return result
