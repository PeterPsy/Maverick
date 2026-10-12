#!/usr/bin/env python3
"""Install operator-managed address/TLS infrastructure beside the Core unit."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def render_service(root: Path, *, root_directory="", core_unit="maverick-core.service") -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.service", core_unit):
        raise ValueError("Invalid Core unit")
    if any(c in str(root) + root_directory for c in '\n\r%"'):
        raise ValueError("Unsupported systemd path")
    inside = str(root)
    env = root_directory.rstrip("/") + inside + "/.env"
    host_root = root_directory.rstrip("/") + inside
    after_tick = f"/usr/bin/python3 {host_root}/scripts/deploy/installation_after_tick.py --root {host_root} --core-unit {core_unit}"
    chroot = f"RootDirectory={root_directory}\nRootDirectoryStartOnly=yes\nMountAPIVFS=yes\n" if root_directory else ""
    return f'''[Unit]
Description=Maverick installation address and TLS worker
After=network-online.target {core_unit}
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory={inside}
{chroot}EnvironmentFile=-{env}
ExecStart=/usr/bin/env -- {inside}/.venv/bin/python {inside}/scripts/deploy/installation_worker.py
ExecStartPost={after_tick}
TimeoutStartSec=15min
UMask=0077
'''


TIMER = '''[Unit]
Description=Resume Maverick installation changes and maintain TLS
[Timer]
OnBootSec=30s
OnUnitInactiveSec=30s
Unit=maverick-installation.service
[Install]
WantedBy=timers.target
'''


def install(core_unit):
    import dbus
    host = Path("/proc/1/root")
    bus = dbus.bus.BusConnection("unix:path=" + str(host / "run/dbus/system_bus_socket"))
    manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"), "org.freedesktop.systemd1.Manager")
    unit = manager.GetUnit(core_unit)
    properties = dbus.Interface(bus.get_object("org.freedesktop.systemd1", unit), "org.freedesktop.DBus.Properties")
    directory = str(properties.Get("org.freedesktop.systemd1.Service", "RootDirectory"))
    root = ROOT
    # When invoked from the ordinary host, remove the service's chroot prefix.
    if directory and str(ROOT).startswith(directory + "/"):
        root = Path(str(ROOT)[len(directory):])
    metadata = ROOT / ".maverick/installation"
    metadata.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = (ROOT / ".env").stat()
    os.chown(metadata, owner.st_uid, owner.st_gid)
    for name, content in [("maverick-installation.service", render_service(root, root_directory=directory, core_unit=core_unit)),
                          ("maverick-installation.timer", TIMER)]:
        path = host / "etc/systemd/system" / name
        path.write_text(content)
        path.chmod(0o644)
    manager.Reload()
    manager.EnableUnitFiles(["maverick-installation.timer"], False, False)
    manager.StartUnit("maverick-installation.timer", "replace")
    manager.StartUnit("maverick-installation.service", "replace")
    return {"installed": True, "service": "maverick-installation.service", "timer": "maverick-installation.timer"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-unit", default="maverick-core.service")
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo.")
    try:
        print(json.dumps(install(arguments.core_unit)))
    except Exception as error:
        print(json.dumps({"error": "worker_installation_failed", "error_type": type(error).__name__}))
        raise SystemExit(1)
