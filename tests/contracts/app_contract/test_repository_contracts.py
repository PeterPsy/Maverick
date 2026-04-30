from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from core.apps.contracts import parse_app_contract_file


REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = REPO_ROOT / "docs" / "reference" / "app_completeness_matrix.md"


def tracked_app_contract_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "apps/*/app_contract.json"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines()]


class AppContractBaselineTest(unittest.TestCase):
    def test_every_app_has_readme_and_parsing_contract(self) -> None:
        for contract_path in sorted(tracked_app_contract_paths()):
            app_root = contract_path.parent
            parsed = parse_app_contract_file(app_root)
            readme_path = app_root / "README.md"
            self.assertTrue(readme_path.exists(), f"{parsed.app_id} is missing README.md")
            readme_text = readme_path.read_text()
            self.assertIn("## SDK Flow", readme_text, f"{parsed.app_id} README is missing SDK Flow")
            self.assertIn("## Contract Notes", readme_text, f"{parsed.app_id} README is missing Contract Notes")

    def test_declared_skill_ids_match_bundled_skill_templates(self) -> None:
        for contract_path in sorted(tracked_app_contract_paths()):
            app_root = contract_path.parent
            contract = json.loads(contract_path.read_text())
            skills_root = contract["entrypoints"].get("skills_root")
            declared = sorted(contract["capabilities"].get("skills") or [])
            if not skills_root:
                self.assertEqual(declared, [], f"{contract['app_id']} declares skills without skills_root")
                continue
            skill_dir = app_root / skills_root
            bundled = sorted(path.parent.name for path in skill_dir.glob("*/SKILL.md"))
            self.assertEqual(
                declared,
                bundled,
                f"{contract['app_id']} capabilities.skills does not match bundled skill ids",
            )

    def test_declared_entrypoints_exist(self) -> None:
        for contract_path in sorted(tracked_app_contract_paths()):
            app_root = contract_path.parent
            contract = json.loads(contract_path.read_text())
            entrypoints = contract["entrypoints"]
            for key in ("frontend", "backend", "cli", "mcp"):
                relative = entrypoints.get(key)
                if relative is None:
                    continue
                self.assertTrue((app_root / relative).exists(), f"{contract['app_id']} missing {key} entrypoint {relative}")
            for hook_name, relative in (entrypoints.get("hooks") or {}).items():
                self.assertTrue((app_root / relative).exists(), f"{contract['app_id']} missing {hook_name} hook {relative}")
            for widget in contract.get("widgets") or []:
                mount = widget.get("frontend", {}).get("mount")
                if mount:
                    self.assertTrue((app_root / mount).exists(), f"{contract['app_id']} missing widget mount {mount}")

    def test_lifecycle_hooks_are_declared_only_when_entrypoints_exist(self) -> None:
        lifecycle_to_hook = {
            "install": "install",
            "migrate": "migrate",
            "health_check": "health_check",
            "uninstall": "uninstall",
        }
        for contract_path in sorted(tracked_app_contract_paths()):
            contract = json.loads(contract_path.read_text())
            hooks = set((contract["entrypoints"].get("hooks") or {}).keys())
            for lifecycle_key, hook_key in lifecycle_to_hook.items():
                self.assertFalse(
                    contract["lifecycle"].get(lifecycle_key) and hook_key not in hooks,
                    f"{contract['app_id']} declares lifecycle.{lifecycle_key} without {hook_key} hook",
                )

    def test_completeness_matrix_mentions_every_app(self) -> None:
        matrix = MATRIX_PATH.read_text()
        for contract_path in sorted(tracked_app_contract_paths()):
            app_id = json.loads(contract_path.read_text())["app_id"]
            self.assertIn(f"`{app_id}`", matrix, f"{app_id} missing from app completeness matrix")

    def test_referenceable_apps_declare_standard_view_surfaces(self) -> None:
        standard_actions = {"view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"}
        for contract_path in sorted(tracked_app_contract_paths()):
            parsed = parse_app_contract_file(contract_path.parent)
            entity_types = {item.entity_type for item in parsed.contract.capabilities.reference_entities}
            if not entity_types:
                continue
            self.assertTrue(parsed.contract.capabilities.view_surfaces, f"{parsed.app_id} has references without view_surfaces")
            resources = {event.resource for event in parsed.contract.capabilities.data_events}
            self.assertIn("view-state", resources, f"{parsed.app_id} has view_surfaces without view-state data event")
            mcp_prefix = parsed.app_id.replace("-", "_")
            for surface in parsed.contract.capabilities.view_surfaces:
                self.assertTrue(set(surface.entity_types).issubset(entity_types))
                actions = {item.action for item in surface.state_actions}
                self.assertTrue(standard_actions.issubset(actions), f"{parsed.app_id} missing standard view state actions")
                if parsed.contract.entrypoints.mcp:
                    for action in standard_actions:
                        self.assertIn(f"{mcp_prefix}_{action}", parsed.contract.capabilities.mcp_tools)
