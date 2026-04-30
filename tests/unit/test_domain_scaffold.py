"""Tests for repository domain module hygiene."""

from pathlib import Path
import unittest

from core.shared.repository import installation_paths


class DomainScaffoldTestCase(unittest.TestCase):
    """Verify domain modules have concrete ownership instead of empty route scaffolds."""

    def test_core_does_not_keep_placeholder_route_modules(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        placeholder_routes = []
        for route_file in sorted((repo_root / "core").glob("*/routes.py")):
            content = route_file.read_text(encoding="utf-8")
            if "route_descriptions" in content and "placeholder" in content.lower():
                placeholder_routes.append(route_file.relative_to(repo_root).as_posix())

        self.assertEqual(placeholder_routes, [])


if __name__ == "__main__":
    unittest.main()
