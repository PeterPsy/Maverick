"""Tests for the initial per-domain scaffold pattern."""

import unittest

from core.apps.routes import route_descriptions as app_routes
from core.identity.routes import route_descriptions as identity_routes
from core.runtime.routes import route_descriptions as runtime_routes
from core.workspaces.routes import route_descriptions as workspace_routes


class DomainScaffoldTestCase(unittest.TestCase):
    """Verify the initial per-domain file pattern is importable and non-empty."""

    def test_apps_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("catalog", app_routes())

    def test_identity_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("users", identity_routes())

    def test_runtime_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("sessions", runtime_routes())

    def test_workspaces_domain_exposes_route_descriptions(self) -> None:
        self.assertIn("registry", workspace_routes())


if __name__ == "__main__":
    unittest.main()
