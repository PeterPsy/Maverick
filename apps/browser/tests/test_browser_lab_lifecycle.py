"""Foreground integration test of the production supervisor's descendant cleanup."""

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest


BACKEND = Path(__file__).resolve().parents[1] / "backend"


def running(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("The supervised fixture did not reach the expected state.")


class BrowserLabLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux" and shutil.which("node"), "Linux/Node lifecycle test")
    def test_wrapper_crash_reaps_grandchild_and_shutdown_reaps_replacements(self):
        with TemporaryDirectory(prefix="browser-lab-lifecycle-") as folder:
            root = Path(folder)
            broker = root / "broker"
            broker.mkdir()
            service = root / "runtime"
            socket_path = service / "lab.sock"
            state_path = root / "playwright.json"
            broker_pid_path = root / "broker.pid"
            grandchild_script = root / "run-server.mjs"
            grandchild_script.write_text("setInterval(() => {}, 1000);\n")
            (broker / "playwright-server-local.mjs").write_text(
                'import {spawn} from "node:child_process";\nimport {writeFileSync} from "node:fs";\n'
                f"const child=spawn(process.execPath,[{json.dumps(str(grandchild_script))}],{{stdio:'ignore'}});\n"
                f"writeFileSync({json.dumps(str(state_path))},JSON.stringify({{parent:process.pid,child:child.pid}}));\n"
                "setInterval(() => {}, 1000);\n"
            )
            (broker / "playwright-broker.mjs").write_text(
                'import {writeFileSync} from "node:fs";\n'
                f"writeFileSync({json.dumps(str(broker_pid_path))},String(process.pid));\n"
                "setInterval(() => {}, 1000);\n"
            )
            launcher = root / "launch.py"
            launcher.write_text(
                "import sys\nfrom pathlib import Path\n"
                f"sys.path.insert(0,{str(BACKEND)!r})\n"
                "import lab_runtime_worker as worker\n"
                f"worker.APP_ROOT=Path({str(root)!r})\n"
                f"worker.SERVICE_ROOT=Path({str(service)!r})\n"
                f"worker.SOCKET_PATH=Path({str(socket_path)!r})\n"
                # Only the network health probe is replaced. The supervision,
                # process groups, private socket and shutdown are production code.
                "worker.broker_health=lambda **kwargs: {'connected':True}\n"
                "worker.main(sys.argv[1])\n"
            )
            process = subprocess.Popen(
                [sys.executable, str(launcher), shutil.which("node")],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                env={key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ},
            )
            owned_groups = set()

            def state():
                try:
                    value = json.loads(state_path.read_text())
                    owned_groups.add(value["parent"])
                    if broker_pid_path.exists():
                        owned_groups.add(int(broker_pid_path.read_text()))
                    return value
                except (FileNotFoundError, ValueError):
                    return None

            def ready():
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode())
                try:
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(1)
                        client.connect(str(socket_path))
                        client.sendall(b'{"action":"status"}\n')
                        return json.loads(client.recv(8192)).get("status") == "ready"
                except (OSError, ValueError):
                    return False

            try:
                first = wait_for(state)
                wait_for(ready)
                os.kill(first["parent"], signal.SIGKILL)
                replacement = wait_for(lambda: (value if (value := state()) and value["parent"] != first["parent"] else None))
                wait_for(lambda: not running(first["child"]))
                wait_for(ready)
                broker_pid = int(broker_pid_path.read_text())
                process.terminate()
                process.wait(timeout=12)
                self.assertEqual(process.returncode, 0)
                for pid in (replacement["parent"], replacement["child"], broker_pid):
                    wait_for(lambda: not running(pid))
                self.assertFalse(socket_path.exists())
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                state()
                for group in owned_groups:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.stderr.close()
