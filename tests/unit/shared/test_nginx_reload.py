"""A reload must target the tested live configuration and the same master."""

from pathlib import Path
import signal
import tempfile
import unittest

from core.installation.nginx_control import reload_nginx, running_master


class NginxReloadTests(unittest.TestCase):
    def test_reload_tests_actual_configuration_and_signals_verified_master(self):
        commands, signals = [], []
        master = (1234, "/etc/nginx/azure-runtime.conf", "500")
        reload_nginx(finder=lambda: master,
                     runner=lambda args, **kwargs: commands.append((args, kwargs)),
                     sender=lambda pid, sig: signals.append((pid, sig)))
        self.assertEqual(commands[0][0], ["/usr/sbin/nginx", "-t", "-c", master[1]])
        self.assertTrue(commands[0][1]["check"])
        self.assertEqual(signals, [(1234, signal.SIGHUP)])

    def test_changed_master_is_never_signaled(self):
        values = iter([(1234, "/etc/nginx/nginx.conf", "500"), (1234, "/etc/nginx/nginx.conf", "501")])
        signals = []
        with self.assertRaises(RuntimeError):
            reload_nginx(finder=lambda: next(values), runner=lambda *args, **kwargs: None,
                         sender=lambda *args: signals.append(args))
        self.assertFalse(signals)

    def test_finder_ignores_commands_that_only_contain_nginx_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for pid, command in [(1234, "nginx: master process /usr/sbin/nginx -c /etc/nginx/azure-runtime.conf -g daemon off;"),
                                 (5555, "python -c print('nginx: master process /usr/sbin/nginx')")]:
                process = root / str(pid)
                process.mkdir()
                (process / "cmdline").write_text(command)
                (process / "stat").write_text(f"{pid} (nginx master) " + " ".join(["0"] * 19 + ["500"]))
            self.assertEqual(running_master(root), (1234, "/etc/nginx/azure-runtime.conf", "500"))


if __name__ == "__main__":
    unittest.main()
