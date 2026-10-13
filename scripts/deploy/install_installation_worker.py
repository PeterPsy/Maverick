#!/usr/bin/env python3
"""Install operator-managed address/TLS infrastructure beside the Core unit."""

import argparse
import json
import os
import pwd
import grp
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


from core.installation.host_units import render_service, TIMER


def service_account_ids(user: str, group: str) -> tuple[int, int]:
    user = user or 'root'
    account = pwd.getpwuid(int(user)) if user.isdecimal() else pwd.getpwnam(user)
    group_id = (int(group) if group.isdecimal() else grp.getgrnam(group).gr_gid) if group else account.pw_gid
    return account.pw_uid, group_id


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
    owner = service_account_ids(str(properties.Get("org.freedesktop.systemd1.Service", "User")),
                               str(properties.Get("org.freedesktop.systemd1.Service", "Group")))
    os.chown(metadata, *owner)
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
