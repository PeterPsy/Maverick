"""Guard the host/chroot path boundary in Azure migration recovery plans."""

from pathlib import Path
import tempfile
import unittest

from scripts.deploy.render_azure_recovery import HOSTNAME, RECOVERY_INCLUDE, SERVICES, render_plan


class AzureRecoveryPlanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="maverick-azure-recovery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.migration = self.root / "migrated-root"
        self.output = self.root / "rendered"
        self.repository = Path(__file__).resolve().parents[3]
        (self.migration / "home/ubuntu/projects/maverick-v3").mkdir(parents=True)
        self._write("etc/passwd", "ubuntu:x:1000:1000:Ubuntu:/home/ubuntu:/bin/bash\n")
        self.runtime = "http {\n    include /etc/nginx/azure-loopino-unified.conf;\n}\n"
        self._write("etc/nginx/azure-runtime.conf", self.runtime)
        for filename in (f"{HOSTNAME}.conf", "maverick-sidecars.loopino.ai.conf"):
            self._write(f"etc/nginx/sites-available/{filename}", "# migrated virtual host\n")
        for service in SERVICES:
            self._write(
                f"etc/systemd/system/{service}",
                "[Service]\nUser=ubuntu\nGroup=ubuntu\n"
                "WorkingDirectory=/home/ubuntu/projects/maverick-v3\n"
                "EnvironmentFile=/home/ubuntu/projects/maverick-v3/.env\n"
                "ExecStart=/home/ubuntu/projects/maverick-v3/.venv/bin/python -m uvicorn\n",
            )
        self._write(
            "etc/systemd/system/maverick-core.service.d/50-sqlite-runtime.conf",
            "[Service]\nEnvironment=LD_LIBRARY_PATH=/home/ubuntu/projects/maverick-v3/.maverick/sqlite/3.51.3/lib\n",
        )

    def _write(self, relative_path: str, content: str) -> None:
        path = self.migration / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def render(self) -> None:
        render_plan(self.migration, self.repository, self.output)

    def test_environment_file_uses_host_path_but_execution_paths_stay_inside_chroot(self) -> None:
        self.render()
        unit = (self.output / "systemd/maverick-core.service").read_text()
        self.assertIn(f"EnvironmentFile={self.migration}/home/ubuntu/projects/maverick-v3/.env\n", unit)
        self.assertIn("WorkingDirectory=/home/ubuntu/projects/maverick-v3\n", unit)
        self.assertIn("ExecStart=/home/ubuntu/projects/maverick-v3/.venv/bin/python", unit)
        dropins = self.output / "systemd/maverick-core.service.d"
        override = (dropins / "zz-azure-migration.conf").read_text()
        self.assertIn(f"RootDirectory={self.migration}\n", override)
        self.assertIn("User=1000\nGroup=1000\n", override)
        operating_group = (self.migration / "home/ubuntu/projects/maverick-v3").stat().st_gid
        self.assertIn(f"SupplementaryGroups={operating_group}\n", override)
        self.assertIn("HOME=/home/ubuntu", override)
        self.assertEqual(
            (dropins / "50-sqlite-runtime.conf").read_bytes(),
            (self.migration / "etc/systemd/system/maverick-core.service.d/50-sqlite-runtime.conf").read_bytes(),
        )

    def test_render_never_changes_migrated_files_or_requires_secret_contents(self) -> None:
        before = {p.relative_to(self.migration): p.read_bytes() for p in self.migration.rglob("*") if p.is_file()}
        self.render()
        after = {p.relative_to(self.migration): p.read_bytes() for p in self.migration.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.migration / "home/ubuntu/projects/maverick-v3/.env").exists())

    def test_nginx_routes_only_requested_hosts_and_acme_phase_does_not_expose_http_apis(self) -> None:
        self.render()
        runtime = (self.output / "azure-runtime.conf").read_text()
        self.assertEqual(runtime, self.runtime.replace("}\n", RECOVERY_INCLUDE + "}\n"))
        https = (self.output / "https.conf").read_text()
        self.assertIn(f"/etc/nginx/sites-available/{HOSTNAME}.conf;", https)
        self.assertIn("/etc/nginx/sites-available/maverick-sidecars.loopino.ai.conf;", https)
        self.assertNotIn("sites-enabled/*", runtime + https)
        http = (self.output / "http.conf").read_text()
        self.assertNotIn("proxy_pass", http)
        self.assertNotIn("ssl_certificate", http)
        self.assertNotIn("{{", http)
        self.assertIn(f"root /var/www/{HOSTNAME};", http)
        self.assertIn("root /var/lib/maverick/browser-origin-acme;", http)
        self._write("etc/nginx/azure-runtime.conf", runtime)
        self.render()
        self.assertEqual((self.output / "azure-runtime.conf").read_text().count(RECOVERY_INCLUDE), 1)

    def test_unknown_nginx_layout_or_privileged_service_identity_fails_before_render(self) -> None:
        self._write("etc/nginx/azure-runtime.conf", "http { include /etc/nginx/sites-enabled/*; }\n")
        with self.assertRaises(ValueError):
            self.render()
        self.assertFalse(self.output.exists())
        self._write("etc/nginx/azure-runtime.conf", self.runtime)
        self._write("etc/passwd", "ubuntu:x:0:0:Ubuntu:/home/ubuntu:/bin/bash\n")
        with self.assertRaises(ValueError):
            self.render()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
