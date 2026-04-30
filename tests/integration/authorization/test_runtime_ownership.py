"""Split tests from tests.support.cases.authorization_integration_cases.AuthorizationIntegrationTestCase."""

from __future__ import annotations

from tests.support.cases import authorization_integration_cases as cases


_SELECTED = {
    'test_runtime_owner_and_workspace_admin_boundaries_are_enforced',
    'test_member_cannot_mint_runtime_operation_grant_from_http_body',
    'test_cross_workspace_runtime_operations_do_not_leak_authority',
    'test_runtime_cli_derives_mode_from_session_not_client_payload',
    'test_runtime_cli_requires_active_owner_workspace_membership',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AuthorizationIntegrationTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AuthorizationRuntimeOwnershipTest(cases.AuthorizationIntegrationTestCase):
    """Run the AuthorizationRuntimeOwnershipTest subset."""

    pass


_mask_unselected(AuthorizationRuntimeOwnershipTest)
