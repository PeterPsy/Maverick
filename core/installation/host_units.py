"""Shared systemd rendering for normal installer and operator deployment."""

from pathlib import Path
import re


def render_service(root: Path, *, root_directory="", core_unit="maverick-core.service") -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.service", core_unit):
        raise ValueError("Invalid Core unit")
    if not root.is_absolute() or any(c.isspace() or c in '%"\\' for c in str(root) + root_directory):
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

