"""Admin-gated MCP operations using the same installation domain as the CLI."""

from pathlib import Path

from core.installation.errors import InstallationError
from core.installation.operations import OPERATIONS, invoke
from core.installation.service import InstallationService
from core.mcp.core_tool_helpers import FULL_ACCESS_WORKSPACE, core_mcp_tool, record_mcp_audit


def installation_tool_specs(*, secret_store=None, app_store=None, workspace_store=None,
                            observability_store=None, start_path: Path | None = None):
    service = InstallationService(start_path or Path.cwd(), secret_store=secret_store,
                                  app_store=app_store, workspace_store=workspace_store)
    result = []
    for operation, (description, arguments, effect) in OPERATIONS.items():
        def handler(payload, context, operation=operation):
            if context.platform_role != "admin" and context.caller_kind != "operator":
                raise InstallationError("admin_required", status=403)
            response = invoke(service, operation, payload, actor_user_id=context.user_id)
            if OPERATIONS[operation][2] != "read":
                record_mcp_audit(observability_store, event_type="core.installation." + operation,
                    workspace_id=context.workspace_id, payload={"actor_user_id": context.user_id, "operation": operation})
            return response
        definition = core_mcp_tool(tool_name="core.installation." + operation,
            description=description, owner_id="installation", invocation_policy=FULL_ACCESS_WORKSPACE,
            input_schema=arguments, effect_class=effect,
            supports_idempotency=operation in {"apply", "rollback", "retry"}, safe_to_retry=True)
        result.append((definition, handler))
    return result
