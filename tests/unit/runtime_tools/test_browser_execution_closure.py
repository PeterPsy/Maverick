from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from core.runtime.hosted_builtin_app_execution import (
    hosted_builtin_app_execution_digest,
    hosted_builtin_app_execution_roots,
)


APPS_ROOT = Path(__file__).resolve().parents[3] / "apps"


class BrowserExecutionClosureTests(unittest.TestCase):
    def test_browser_read_authority_changes_when_reachable_broker_source_changes(self) -> None:
        roots = hosted_builtin_app_execution_roots("browser", surface="mcp", apps_root=APPS_ROOT)
        self.assertIn("broker/reading-actions.mjs", roots)
        self.assertIn("broker/snapshot-reference.mjs", roots)
        self.assertIn("broker/platform-auth.mjs", roots)
        self.assertIn("package-lock.json", roots)
        self.assertIn("companion/worker.mjs", roots)
        self.assertIn("companion/agent-tab.mjs", roots)
        self.assertIn("companion/setup.mjs", roots)
        self.assertIn("companion/interaction-controller.mjs", roots)
        self.assertIn("companion/interaction-dom.mjs", roots)
        self.assertIn("companion/interaction-inputs.mjs", roots)
        self.assertIn("companion/website-scope.mjs", roots)
        self.assertIn("companion/platforms.json", roots)
        self.assertIn("companion/platforms.mjs", roots)
        self.assertIn("frontend/dist", roots)
        with TemporaryDirectory() as folder:
            apps = Path(folder)
            browser = apps / "browser"
            for relative in roots:
                source = APPS_ROOT / "browser" / relative
                target = browser / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    shutil.copyfile(source, target)
            before = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            broker_source = browser / "broker" / "reading-actions.mjs"
            broker_source.write_text(broker_source.read_text() + "\n// changed broker source\n")
            after = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            companion_source = browser / "companion" / "worker.mjs"
            companion_source.write_text(companion_source.read_text() + "\n// changed companion source\n")
            companion_changed = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            reference_source = browser / "broker" / "snapshot-reference.mjs"
            reference_source.write_text(reference_source.read_text() + "\n// changed reference resolution\n")
            reference_changed = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            policy_source = browser / "companion" / "platforms.json"
            policy_source.write_text(policy_source.read_text() + "\n")
            policy_changed = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            authentication_source = browser / "broker" / "platform-auth.mjs"
            authentication_source.write_text(authentication_source.read_text() + "\n// changed authentication\n")
            authentication_changed = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            identity_source = browser / "companion" / "agent-tab.mjs"
            identity_source.write_text(identity_source.read_text() + "\n// changed agent identity\n")
            identity_changed = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
            setup_source = browser / "companion" / "setup.mjs"
            setup_source.write_text(setup_source.read_text() + "\n// changed reconnect validation\n")
            setup_changed = hosted_builtin_app_execution_digest("browser", surface="mcp", apps_root=apps)
        self.assertNotEqual(before, after)
        self.assertNotEqual(after, companion_changed)
        self.assertNotEqual(companion_changed, reference_changed)
        self.assertNotEqual(reference_changed, policy_changed)
        self.assertNotEqual(policy_changed, authentication_changed)
        self.assertNotEqual(authentication_changed, identity_changed)
        self.assertNotEqual(identity_changed, setup_changed)
