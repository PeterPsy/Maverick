"""Split tests from tests.support.cases.authorization_integration_cases.AuthorizationIntegrationTestCase."""

from __future__ import annotations

from tests.support.cases import authorization_integration_cases as cases


_SELECTED = {
    'test_runtime_restart_cli_and_mcp_use_owner_admin_and_grants_not_agent_id_spoofing',
    'test_runtime_restart_cli_and_mcp_use_owner_admin_and_grant_authority',
    'test_backend_restart_requires_admin_capability_on_cli_and_mcp',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AuthorizationIntegrationTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AuthorizationRestartPermissionsTest(cases.AuthorizationIntegrationTestCase):
    """Run the AuthorizationRestartPermissionsTest subset."""

    pass


_mask_unselected(AuthorizationRestartPermissionsTest)
