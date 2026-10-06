"""Lifecycle control for Browser's Core-hosted, installation-local Lab worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT.parents[1] / "runtime/browser"
SOCKET_PATH = SERVICE_ROOT / "lab.sock"


def control(action: str) -> dict:
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(SOCKET_PATH))
            client.sendall(json.dumps({"action": action}).encode() + b"\n")
            data = client.recv(8192)
            return json.loads(data)
    except (OSError, ValueError):
        return {"status": "stopped"}


def configure(enabled: bool) -> None:
    SERVICE_ROOT.mkdir(parents=True, exist_ok=True)
    path = SERVICE_ROOT / "lab-enabled"
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("yes" if enabled else "no")


def ensure_running(*, enable: bool = False) -> dict:
    if enable:
        configure(True)
    flag = SERVICE_ROOT / "lab-enabled"
    if not flag.is_file() or flag.is_symlink() or flag.read_text() != "yes":
        return {"status": "disabled"}
    current = control("status")
    if current.get("status") != "stopped":
        return current
    node = shutil.which("node")
    if not node:
        return {"status": "failed", "error": "node_runtime_unavailable"}
    subprocess.run([node, str(APP_ROOT.parents[1] / "scripts/check-node-runtime.mjs")], check=True, capture_output=True, timeout=5)
    # The host's install/recovery hooks start this app runtime worker. It remains
    # in Core's service cgroup and is shut down with the backend; recovery reopens it.
    subprocess.Popen([sys.executable, str(Path(__file__).with_name("lab_runtime_worker.py")), node],
                     cwd=APP_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                     env={key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "PLAYWRIGHT_BROWSERS_PATH") if key in os.environ})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = control("status")
        if current.get("status") == "ready":
            return current
        time.sleep(0.1)
    return current if current.get("status") != "stopped" else {"status": "failed", "error": "lab_worker_start_failed"}


def stop() -> dict:
    configure(False)
    return control("stop")
