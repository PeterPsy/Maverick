"""Optional source-app scope is a narrowing filter, never actor authority."""
from .errors import AppError


SCOPED_ACTIONS = {"list", "get", "publish.plan", "publish.apply", "rollback.plan", "rollback.apply",
                  "suspend", "archive", "plan.approve"}


def assert_source_scope(store, ctx, body):
    source = body.get("source_app_id")
    if not source:
        return
    if body.get("action") == "publish.plan" and source != ctx.provider_id:
        raise AppError("source_exporter_not_selected", 409)
    if body.get("plan_id") and store.get("plans", body["plan_id"])["provider_id"] != source:
        raise AppError("not_found", 404)
    if body.get("external_app_id") and store.get("apps", body["external_app_id"])["provider_id"] != source:
        raise AppError("not_found", 404)
