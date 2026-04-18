"""Tests for the initial per-domain scaffold pattern."""

import unittest

from core.apps.routes import route_descriptions as app_routes
from core.cli.routes import route_descriptions as cli_routes
from core.identity.routes import route_descriptions as identity_routes
from core.mcp.routes import route_descriptions as mcp_routes
from core.providers.routes import route_descriptions as provider_routes
from core.runtime.routes import route_descriptions as runtime_routes
from core.skills.routes import route_descriptions as skill_routes
from core.workspaces.routes import route_descriptions as workspace_routes


class DomainScaffoldTestCase(unittest.TestCase):
    """Verify the initial per-domain file pattern is importable and non-empty."""

    def test_apps_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("catalog", app_routes())

    def test_identity_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("users", identity_routes())

    def test_mcp_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("registry", mcp_routes())

    def test_cli_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("runner", cli_routes())

    def test_skills_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("catalog", skill_routes())

    def test_providers_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("registry", provider_routes())

    def test_runtime_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("sessions", runtime_routes())

    def test_workspaces_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("registry", workspace_routes())


if __name__ == "__main__":
    unittest.main()
