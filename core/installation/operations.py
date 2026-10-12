"""One operation catalog shared by HTTP, CLI and MCP."""

from core.installation.errors import InstallationError
from core.runtime.tool_schema import validate_tool_arguments
from core.runtime.tool_errors import RuntimeToolSchemaError

TEXT = {"type": "string", "minLength": 1, "maxLength": 512}
IDENTIFIER = {"type": "string", "minLength": 32, "maxLength": 32}


def schema(properties=None, required=None):
    return {"type": "object", "additionalProperties": False,
            "properties": properties or {}, "required": required or []}


OPERATIONS = {
    "inspect": ("Inspect installation address, DNS connection, worker and services.", schema(), "read"),
    "plan": ("Prepare an installation address plan without changing DNS or the host.",
        schema({"address": TEXT, "target_ip": TEXT,
                "dns_provider": {"type": "string", "enum": ["cloudflare", "manual"]},
                "dns_secret_ref": TEXT}, ["address", "target_ip"]), "mutating"),
    "apply": ("Queue one reviewed, idempotent installation address plan.",
        schema({"plan_id": IDENTIFIER, "confirmed_actions": {"type": "array", "items": TEXT, "maxItems": 128}}, ["plan_id"]), "mutating"),
    "status": ("Read a durable installation job and its plan.", schema({"job_id": IDENTIFIER}, ["job_id"]), "read"),
    "confirm": ("Confirm completed external provider registrations for one job.",
        schema({"job_id": IDENTIFIER, "action_ids": {"type": "array", "items": TEXT, "maxItems": 128}}, ["job_id", "action_ids"]), "mutating"),
    "retry": ("Resume a recoverable installation job without duplicating changes.", schema({"job_id": IDENTIFIER}, ["job_id"]), "mutating"),
    "verify": ("Verify live main, app-frame and sidecar HTTPS for this installation.", schema(), "read"),
    "rollback": ("Queue selective restoration of one installation change.", schema({"job_id": IDENTIFIER}, ["job_id"]), "destructive"),
}


def invoke(service, operation: str, arguments: dict, *, actor_user_id=None):
    if operation not in OPERATIONS:
        raise InstallationError("installation_operation_not_found", status=404)
    specification = OPERATIONS[operation][1]
    try:
        validate_tool_arguments(specification, arguments)
    except RuntimeToolSchemaError:
        raise InstallationError("invalid_installation_arguments") from None
    if operation in {"inspect", "verify"}:
        return getattr(service, operation)()
    if operation == "status":
        return service.status(arguments["job_id"])
    return getattr(service, operation)(**arguments, actor_user_id=actor_user_id)
