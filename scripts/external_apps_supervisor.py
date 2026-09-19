"""Operator deployment supervisor; foreground only, never boots the active backend.

The public child receives no Core stores, secrets, environment or workspace roots.
Canonical hosting state is read-only; interrupted app-owned publications are recovered.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY / "apps/external-apps"
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.apps.store import AppDocumentStore
from core.apps.surfaces import resolve_workspace_app_surface
from core.workspaces.store import WorkspaceDocumentStore
from external_apps.deployment import load as load_deployment
from external_apps.files import atomic_write, encoded, publication_lock
from external_apps.operations import recover
from external_apps.policy import domain_name
from external_apps.store import Store
from public_server.confinement import command


def selected_mounts(app_store, workspace_store, *, selections, domain, repository=REPOSITORY):
    """Select declared operator targets with live workspace/app/source checks."""
    roots = {}
    duplicates = set()
    if not isinstance(selections, list) or len(selections) > 64:
        raise ValueError("invalid_workspace_selection")
    for selection in selections:
        try:
            workspace_id = selection["workspace_id"]
            local_id = selection.get("local_app_id", "external-apps")
            if workspace_store.get_workspace(workspace_id).status != "active":
                continue
            binding = app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=local_id)
            if binding.status != "enabled" or binding.source_kind != "platform":
                continue
            source_root, parsed = resolve_workspace_app_surface(app_store, binding=binding, start_path=repository)
            if source_root.resolve() != (repository / "apps/external-apps").resolve() or parsed.contract.distribution.mode != "sealed":
                continue
            root = Path(binding.data_root)
            expected = repository / "workspaces" / workspace_id / "data" / local_id
            if root.resolve() != expected.resolve() or any(path.is_symlink() for path in (root, *root.parents)):
                continue
            config = load_deployment(root)
            public = root / "public"
            if config["domain"] != domain or not public.is_dir() or public.is_symlink():
                continue
            # OS leases distinguish a live verifier from a killed entrypoint.
            # Reconcile before refreshing serving authority, without backend restart.
            store = Store(root, workspace_id)
            store.assert_workspace()
            with publication_lock(root):
                recover(store)
            namespace = config["namespace"]
            if namespace in roots or namespace in duplicates:
                duplicates.add(namespace)
                roots.pop(namespace, None)
                continue
            roots[namespace] = public
        except (KeyError, OSError):
            continue
        except Exception:
            # Invalid/missing live authority removes a mount, never preserves it.
            continue
    return roots


def run(config, *, app_store, workspace_store):
    domain = domain_name(config["domain"])
    state_dir = Path(config["state_directory"])
    listener_dir = Path(config["listener_directory"])
    if (not state_dir.is_absolute() or not listener_dir.is_absolute()
            or state_dir == listener_dir or state_dir in listener_dir.parents or listener_dir in state_dir.parents
            or any(p.is_symlink() for path in (state_dir, listener_dir) for p in (path, *path.parents))):
        raise ValueError("invalid_service_directories")
    state_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    listener_dir.mkdir(mode=0o770, parents=True, exist_ok=True)
    projection = state_dir / "mounts.json"
    child = None
    previous = None
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            roots = selected_mounts(app_store, workspace_store, selections=config["workspaces"], domain=domain)
            signature = [(namespace, str(path), path.stat().st_dev, path.stat().st_ino) for namespace, path in sorted(roots.items())]
            if signature != previous:
                atomic_write(projection, encoded({"version": 1, "domain": domain, "namespaces": [], "expires": time.time()}))
                terminate(child)
                child = None
                socket_path = listener_dir / "public.sock"
                if socket_path.exists():
                    if not socket_path.is_socket():
                        raise RuntimeError("unsafe_listener_path")
                    socket_path.unlink()
                args = command(app_root=APP_ROOT, public_roots=roots, projection_directory=state_dir,
                               listener_directory=listener_dir, domain=domain)
                child = subprocess.Popen(args, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, stdin=subprocess.DEVNULL)
                previous = signature
            if child is None or child.poll() is not None:
                raise RuntimeError("confined_runtime_failed")
            # Readiness means an actual socket round-trip, not process presence.
            if not listener_healthy(listener_dir / "public.sock"):
                atomic_write(projection, encoded({"version": 1, "domain": domain, "namespaces": [], "expires": time.time()}))
            else:
                atomic_write(projection, encoded({"version": 1, "domain": domain, "namespaces": sorted(roots), "expires": time.time() + 8}))
            time.sleep(2)
    finally:
        atomic_write(projection, encoded({"version": 1, "domain": domain, "namespaces": [], "expires": time.time()}))
        terminate(child)


def listener_healthy(path):
    import socket
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(1)
            sock.connect(str(path))
            sock.sendall(b"GET / HTTP/1.0\r\nHost: invalid\r\n\r\n")
            return sock.recv(128).startswith(b"HTTP/1.0 404")
    except OSError:
        return False


def terminate(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    # No bootstrap_platform_state: it performs cleanup and runtime/key initialization.
    settings = ControlStoreSettings.from_environment(repository_root=REPOSITORY)
    collections = build_control_plane_collections(settings)
    run(config, app_store=AppDocumentStore(collections.apps), workspace_store=WorkspaceDocumentStore(collections.workspace))


if __name__ == "__main__":
    main()
