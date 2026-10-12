"""A TLS-mode switch must preserve installation credentials and recover failed reloads."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("wildcard_transition", ROOT / "scripts/deploy/activate_browser_origin_wildcard.py")
transition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transition)


class WildcardTransitionTests(unittest.TestCase):
    def test_mode_update_preserves_other_settings_and_removes_conflicting_duplicates(self):
        before = '# installation\nPROVIDER_SECRET="dummy-$`\\value"\nMAVERICK_BROWSER_ORIGIN_TLS_MODE=managed_exact\nOTHER=keep\nexport MAVERICK_BROWSER_ORIGIN_TLS_MODE=managed_exact\n'
        result = transition.external_tls_environment(before)
        self.assertEqual(result, '# installation\nPROVIDER_SECRET="dummy-$`\\value"\nMAVERICK_BROWSER_ORIGIN_TLS_MODE=external_wildcard\nOTHER=keep\n')
        self.assertEqual(transition.external_tls_environment('OTHER=keep'), 'OTHER=keep\nMAVERICK_BROWSER_ORIGIN_TLS_MODE=external_wildcard\n')

    def test_failed_nginx_test_restores_original_config_and_never_enables_wildcard(self):
        with tempfile.TemporaryDirectory() as folder:
            nginx, env = Path(folder, "nginx.conf"), Path(folder, "installation.env")
            nginx.write_text("original routing"); env.write_text("MAVERICK_BROWSER_ORIGIN_TLS_MODE=managed_exact\nOTHER=keep\n")
            original_env = env.read_bytes()
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                if "-t" in command:
                    self.assertEqual(env.read_bytes(), original_env)
                    raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                transition.apply_transition(nginx, env, "invalid routing", runner=runner)
            self.assertEqual(nginx.read_text(), "original routing")
            self.assertEqual(env.read_bytes(), original_env)
            self.assertEqual(len(calls), 2)

    def test_failed_reload_restores_both_files_and_the_original_environment_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            nginx, env = Path(folder, "nginx.conf"), Path(folder, "installation.env")
            nginx.write_text("original routing"); env.write_text("MAVERICK_BROWSER_ORIGIN_TLS_MODE=managed_exact\nOTHER=keep\n")
            env.chmod(0o600)
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                if len(calls) == 2:
                    self.assertIn("external_wildcard", env.read_text())
                    raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                transition.apply_transition(nginx, env, "wildcard routing", runner=runner)
            self.assertEqual(nginx.read_text(), "original routing")
            self.assertEqual(env.read_text(), "MAVERICK_BROWSER_ORIGIN_TLS_MODE=managed_exact\nOTHER=keep\n")
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
