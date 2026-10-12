#!/usr/bin/env python3
"""Host-side completion: restart Core and hand off legacy TLS maintenance."""

import argparse
import json
from pathlib import Path
import re


def complete(root: Path, core_unit: str) -> None:
    import dbus
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.service", core_unit):
        raise ValueError("Invalid Core unit")
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"), "org.freedesktop.systemd1.Manager")
    metadata = root / ".maverick/installation"
    configuration = metadata / "configuration/current.json"
    if configuration.exists() and json.loads(configuration.read_text()).get("managed"):
        try:
            manager.StopUnit("maverick-wildcard-tls.timer", "replace")
            manager.DisableUnitFiles(["maverick-wildcard-tls.timer"], False)
        except dbus.DBusException as error:
            if error.get_dbus_name() not in {"org.freedesktop.systemd1.NoSuchUnit", "org.freedesktop.systemd1.UnitFileNotFound"}:
                raise
    marker = metadata / "private/restart-required"
    if marker.exists():
        manager.RestartUnit(core_unit, "replace")
        # systemd orders the restart; the next tick proves the fresh backend.
        marker.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--core-unit", default="maverick-core.service")
    args = parser.parse_args()
    complete(args.root, args.core_unit)
