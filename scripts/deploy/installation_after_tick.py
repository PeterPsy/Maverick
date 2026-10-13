#!/usr/bin/env python3
"""Host-side completion: restart Core and hand off legacy TLS maintenance."""

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.installation.legacy_timer import handoff_legacy_timer


def complete(root: Path, core_unit: str) -> None:
    import dbus
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.service", core_unit):
        raise ValueError("Invalid Core unit")
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"), "org.freedesktop.systemd1.Manager")
    metadata = root / ".maverick/installation"
    configuration = metadata / "configuration/current.json"
    marker = metadata / "private/restart-required"
    def is_active(name):
        try:
            unit = manager.GetUnit(name)
        except dbus.DBusException as error:
            if error.get_dbus_name() == "org.freedesktop.systemd1.NoSuchUnit":
                return False
            raise
        properties = dbus.Interface(bus.get_object("org.freedesktop.systemd1", unit), "org.freedesktop.DBus.Properties")
        return str(properties.Get("org.freedesktop.systemd1.Unit", "ActiveState")) == "active"
    if configuration.exists():
        try:
            handoff_legacy_timer(manager, metadata / "private",
                managed=bool(json.loads(configuration.read_text()).get("managed")),
                restoring=marker.exists(), is_active=is_active)
        except dbus.DBusException as error:
            if error.get_dbus_name() not in {"org.freedesktop.systemd1.NoSuchUnit", "org.freedesktop.systemd1.UnitFileNotFound"}:
                raise
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
