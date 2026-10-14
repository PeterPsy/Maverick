"""Real isolated startup excludes ambient Python and Certbot configuration."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from core.installation.host_units import render_service
from core.installation.privileged_context import prepare_privileged_context
from core.shared.installation_material import certbot_executable, certbot_directory_arguments

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.geteuid() == 0, "Privileged namespace/startup verification requires root")
class PrivilegedStartupTests(unittest.TestCase):
    def test_system_after_tick_and_worker_ignore_core_user_site_before_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            prepare_privileged_context(root)
            core_home = root / "core-home"
            site_root = core_home / f".local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
            site_root.mkdir(parents=True)
            marker = root / "ambient-user-site-was-loaded"
            (site_root / "usercustomize.py").write_text(f"from pathlib import Path; Path({str(marker)!r}).touch()\n")
            unit = render_service(root)
            for key in ("ExecStart=", "ExecStartPost="):
                command = shlex.split(next(line[len(key):] for line in unit.splitlines() if line.startswith(key)))
                # Replace only the product script with a harmless startup probe.
                prefix = command[:command.index("-I") + 1]
                if key == "ExecStart=":
                    prefix[prefix.index(str(root / ".venv/bin/python"))] = str(ROOT / ".venv/bin/python")
                probe = "import json,os,site,sys; print(json.dumps([os.environ['HOME'],sys.flags.isolated,site.ENABLE_USER_SITE]))"
                result = subprocess.run([*prefix, "-c", probe], capture_output=True, text=True,
                    env={**os.environ, "HOME": str(core_home), "PYTHONPATH": str(site_root), "PYTHONUSERBASE": str(core_home / ".local")})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [str(root / "installation/privileged-home"), 1, False])
                self.assertFalse(marker.exists())

    def test_actual_certbot_never_reads_synthetic_host_or_core_home_defaults(self):
        import certbot
        distribution = Path(certbot.__file__).parent
        primary = [distribution / "_internal/constants.py", distribution / "_internal/cli/helpful.py"]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in primary}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ambient = root / "ambient-host"; ambient.mkdir()
            invalid = "loopino-ambient-config-must-not-be-read = true\n"
            (ambient / "cli.ini").write_text(invalid)
            core_home = root / "core-home"
            user_config = core_home / ".config/letsencrypt"; user_config.mkdir(parents=True)
            (user_config / "cli.ini").write_text(invalid)
            # The outer namespace supplies a synthetic host default without
            # reading or changing the actual /etc/letsencrypt contents.
            probe = '''import os, subprocess, sys
subprocess.run(["/usr/bin/mount", "--bind", sys.argv[1], "/etc/letsencrypt"], check=True)
os.execv(sys.argv[2], sys.argv[2:])
'''
            result = subprocess.run(["/usr/bin/unshare", "--mount", "--propagation", "private",
                "/usr/bin/python3", "-I", "-c", probe, str(ambient), str(certbot_executable(ROOT)),
                "plugins", "--text", *certbot_directory_arguments(ROOT)],
                env={**os.environ, "HOME": str(core_home), "XDG_CONFIG_HOME": str(core_home / ".config")},
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("dns-cloudflare", result.stdout)
            self.assertNotIn("ambient-config", result.stdout + result.stderr)
            config = ROOT / "installation/tls/certbot/cli.ini"
            self.assertEqual(config.stat().st_uid, 0)
            self.assertFalse(config.stat().st_mode & 0o022)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in primary})

    def test_operator_cannot_select_an_unprotected_cli_config(self):
        result = subprocess.run([str(certbot_executable(ROOT)), "plugins", "--config", "/nonexistent/core-owned.ini"],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("configuration is fixed", result.stderr)
