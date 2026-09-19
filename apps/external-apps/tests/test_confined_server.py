"""Opt-in Linux sandbox proof, with a real anonymous HTTP Unix listener."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

from support import APP_ROOT, apply_args, approve, prepare, service
from external_apps.deployment import load
from external_apps.files import atomic_write, encoded
from public_server.confinement import command


@unittest.skipUnless(os.environ.get("EXTERNAL_APPS_CONFINEMENT_TEST") == "1", "opt-in Linux confinement proof")
class ConfinedServerTests(unittest.TestCase):
    def test_real_confined_listener_with_no_private_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            app = service(base / "workspace/data/external-apps")
            plan = approve(app, prepare(app))
            app.handle(apply_args(plan))
            config = load(app.root)
            state, listener = base / "state", base / "listener"
            state.mkdir(); listener.mkdir()
            atomic_write(state / "mounts.json", encoded({"version": 1, "domain": config["domain"], "namespaces": [config["namespace"]], "expires": time.time() + 8}))
            args = command(app_root=APP_ROOT, public_roots={config["namespace"]: app.root / "public"}, projection_directory=state, listener_directory=listener, domain=config["domain"])
            self.assertNotIn(str(app.root / "app.sqlite"), args)
            self.assertIn("--unshare-all", args)
            self.assertNotIn("--share-net", args)
            with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin"}) as process:
                try:
                    deadline = time.monotonic() + 5
                    while not (listener / "public.sock").exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.05)
                    if process.poll() is not None:
                        self.fail("Confined process failed: " + process.stderr.read().decode())
                    self.assertTrue((listener / "public.sock").exists())
                    with socket.socket(socket.AF_UNIX) as sock:
                        sock.settimeout(2)
                        sock.connect(str(listener / "public.sock"))
                        sock.sendall(f"GET / HTTP/1.0\r\nHost: {plan['hostname']}\r\n\r\n".encode())
                        response = b""
                        while chunk := sock.recv(65536):
                            response += chunk
                    self.assertIn(b"200 OK", response)
                    self.assertIn(plan["release_id"].encode(), response)
                    self.assertNotIn(b"Set-Cookie", response)
                    # Within the same sandbox, private source/catalog paths are absent.
                    prefix = args[:args.index("--chdir")]
                    with socket.socket() as private_listener:
                        private_listener.bind(("127.0.0.1", 0)); private_listener.listen(1)
                        private_port = private_listener.getsockname()[1]
                        program = ("import os,socket; assert not os.path.exists('/app.sqlite'); "
                                   "assert not os.path.exists('/home/ubuntu'); assert not os.path.exists('/data/control-plane'); "
                                   "assert os.listdir('/sites'); assert 'MAVERICK_API_TOKEN' not in os.environ; "
                                   "s=socket.socket(); s.settimeout(.2); "
                                   f"assert s.connect_ex(('127.0.0.1',{private_port})) != 0; print('isolated')")
                        proof = subprocess.run(prefix + ["/usr/bin/python3", "-c", program], capture_output=True, text=True, timeout=5)
                        self.assertEqual(proof.returncode, 0, proof.stderr)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
