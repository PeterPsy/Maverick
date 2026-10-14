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
from core.installation.protected_material import prepare_host_logs, protect_service_environment
from core.installation.privileged_context import prepare_privileged_context
from core.shared.env_file import service_env_path
from core.shared.installer import run_privileged_command
from core.installation.registrations import installation_backing_path, registration_exists, register_file, unregister_file


def register_worker_units(root: Path, host: Path, contents: dict[str, str], *, host_backing_root: Path, activate=None) -> None:
    """Keep unit bytes in the installation; roll back our registrations on failure."""
    snapshots = []
    for name, content in contents.items():
        backing = installation_backing_path(root, "systemd", name)
        registration = host / "etc/systemd/system" / name
        target = host_backing_root / "installation/systemd" / name
        registered = registration_exists(registration, target)
        snapshots.append((backing, registration, target, registered, backing.read_bytes() if backing.exists() else None, content))
    try:
        for backing, registration, target, _, _, content in snapshots:
            backing.parent.mkdir(parents=True, exist_ok=True)
            backing.write_text(content)
            backing.chmod(0o644)
            register_file(registration, target)
        if activate is not None:
            activate()
    except BaseException:
        for backing, registration, target, registered, previous, _ in reversed(snapshots):
            if not registered:
                unregister_file(registration, target)
            if previous is None:
                backing.unlink(missing_ok=True)
            else:
                backing.write_bytes(previous)
        raise


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
    metadata = ROOT / ".loopino/installation"
    metadata.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = service_account_ids(str(properties.Get("org.freedesktop.systemd1.Service", "User")),
                               str(properties.Get("org.freedesktop.systemd1.Service", "Group")))
    os.chown(metadata, *owner)
    protect_service_environment(service_env_path(ROOT), str(owner[1]), run_privileged_command)
    prepare_host_logs(ROOT)
    prepare_privileged_context(ROOT)
    def activate():
        manager.Reload()
        manager.EnableUnitFiles(["loopino-installation.timer"], False, False)
        manager.StartUnit("loopino-installation.timer", "replace")
        manager.StartUnit("loopino-installation.service", "replace")

    register_worker_units(ROOT, host, {
        "loopino-installation.service": render_service(root, root_directory=directory, core_unit=core_unit),
        "loopino-installation.timer": TIMER,
    }, host_backing_root=Path(directory) / root.relative_to("/") if directory else root, activate=activate)
    return {"installed": True, "service": "loopino-installation.service", "timer": "loopino-installation.timer"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-unit", default="loopino-core.service")
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo.")
    try:
        print(json.dumps(install(arguments.core_unit)))
    except Exception as error:
        print(json.dumps({"error": "worker_installation_failed", "error_type": type(error).__name__}))
        raise SystemExit(1)
