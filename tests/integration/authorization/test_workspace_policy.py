"""Split tests from tests.support.cases.authorization_integration_cases.AuthorizationIntegrationTestCase."""

from __future__ import annotations

from tests.support.cases import authorization_integration_cases as cases


_SELECTED = {
    'test_workspace_admin_controls_provider_selection_governance_and_membership',
    'test_runtime_creation_obeys_workspace_governance_flags_and_quota',
    'test_app_cli_and_mcp_visibility_follow_workspace_roles',
    'test_visibility_capabilities_are_enforced_for_app_surfaces',
    'test_app_dependency_selection_requires_workspace_admin_but_lookup_is_readable',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AuthorizationIntegrationTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AuthorizationWorkspacePolicyTest(cases.AuthorizationIntegrationTestCase):
    """Run the AuthorizationWorkspacePolicyTest subset."""

    pass


_mask_unselected(AuthorizationWorkspacePolicyTest)
