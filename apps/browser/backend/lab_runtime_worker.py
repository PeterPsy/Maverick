"""Supervise finite Lab sessions under the Maverick backend service lifecycle."""

from __future__ import annotations

import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

from broker_client import broker_health
from lab_runtime_control import APP_ROOT, SERVICE_ROOT, SOCKET_PATH


def main(node: str) -> None:
    os.environ["MAVERICK_BROWSER_BROKER_TIMEOUT_SECONDS"] = "2"
    SERVICE_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(SERVICE_ROOT / "lab.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        token = SERVICE_ROOT / "playwright-broker-token"
        if token.is_symlink():
            raise ValueError("Browser credentials must not be a symlink.")
        if token.exists():
            token.chmod(0o600)
        logger = logging.getLogger("browser-lab")
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(SERVICE_ROOT / "lab.log", maxBytes=1024*1024, backupCount=2)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s")); logger.addHandler(handler)
        (SERVICE_ROOT / "lab.log").chmod(0o600)
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
        cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/home/ubuntu/.cache/ms-playwright"))
        env.update({"PLAYWRIGHT_BROWSERS_PATH": str(cache), "MAVERICK_BROWSER_BROKER_TOKEN_FILE": str(token)})
        stopped = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
        signal.signal(signal.SIGINT, lambda *_: stopped.set())
        scripts = {"playwright": "broker/playwright-server-local.mjs", "broker": "broker/playwright-broker.mjs"}
        children = {}; restarted = {name: 0 for name in scripts}; health = {"status": "starting"}

        def record_output(name, child):
            for line in child.stdout:
                logger.info("%s: %s", name, line.strip()[:1000])

        with socket.socket(socket.AF_UNIX) as server:
            SOCKET_PATH.unlink(missing_ok=True); server.bind(str(SOCKET_PATH)); SOCKET_PATH.chmod(0o600)
            server.listen(4); server.settimeout(0.3)
            try:
                while not stopped.is_set():
                    for name, script in scripts.items():
                        child = children.get(name)
                        if child is None or child.poll() is not None:
                            if time.monotonic()-restarted[name] < 3:
                                continue
                            restarted[name] = time.monotonic()
                            child = subprocess.Popen([node, str(APP_ROOT / script)], cwd=APP_ROOT, env=env,
                                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                     text=True, close_fds=True, start_new_session=True)
                            children[name] = child
                            threading.Thread(target=record_output, args=(name,child), daemon=True).start()
                    if all(child.poll() is None for child in children.values()) and len(children) == 2:
                        health = broker_health(connect=True)
                    try:
                        client, _ = server.accept()
                    except TimeoutError:
                        continue
                    with client:
                        client.settimeout(1)
                        _, uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.getuid():
                            continue
                        try:
                            request = json.loads(client.recv(1024))
                            if request.get("action") == "stop":
                                stopped.set(); result = {"status": "stopping"}
                            else:
                                result = {"status": "ready" if health.get("connected") else "starting", "provider": "core_hosted_worker", "children": {name: child.poll() is None for name,child in children.items()}}
                            client.sendall(json.dumps(result).encode())
                        except (OSError, ValueError):
                            pass
            finally:
                for child in children.values():
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                for child in children.values():
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=5)
                SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main(sys.argv[1])
