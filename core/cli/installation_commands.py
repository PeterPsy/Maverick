"""Admin-only native CLI operations for standalone installation setup."""

from pathlib import Path

from core.cli.core_command_helpers import FULL_ACCESS_ADMIN, core_cli_command, record_cli_audit
from core.installation.errors import InstallationError
from core.installation.operations import OPERATIONS, invoke
from core.installation.service import InstallationService


def installation_command_specs(*, secret_store=None, app_store=None, workspace_store=None,
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
                record_cli_audit(observability_store, action="core.installation." + operation,
                    detail="Installation administration", workspace_id=context.workspace_id,
                    payload={"actor_user_id": context.user_id, "operation": operation})
            return {"command_id": "core.installation." + operation, **response}
        definition = core_cli_command(command_id="core.installation." + operation,
            path_segments=["core", "installation", operation], description=description,
            owner_id="installation", invocation_policy=FULL_ACCESS_ADMIN, argument_schema=arguments,
            effect_class=effect, supports_idempotency=operation in {"apply", "rollback", "retry"},
            safe_to_retry=True)
        result.append((definition, handler))
    return result
