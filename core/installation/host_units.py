"""Shared systemd rendering for normal installer and operator deployment."""

from pathlib import Path
import re
from core.installation.privileged_context import privileged_exec_environment


def render_service(root: Path, *, root_directory="", core_unit="loopino-core.service", environment_path: Path | None = None) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.service", core_unit):
        raise ValueError("Invalid Core unit")
    if not root.is_absolute() or any(c.isspace() or c in '%"\\' for c in str(root) + root_directory):
        raise ValueError("Unsupported systemd path")
    inside = str(root)
    env = root_directory.rstrip("/") + str(environment_path or root / ".env.loopino")
    host_root = root_directory.rstrip("/") + inside
    after_tick = f"{privileged_exec_environment(Path(host_root))} /usr/bin/python3 -I {host_root}/scripts/deploy/installation_after_tick.py --root {host_root} --core-unit {core_unit}"
    chroot = f"RootDirectory={root_directory}\nRootDirectoryStartOnly=yes\nMountAPIVFS=yes\n" if root_directory else ""
    return f'''[Unit]
Description=Loopino installation address and TLS worker
After=network-online.target {core_unit}
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory={inside}
{chroot}Environment=PATH={inside}/.venv/bin:{inside}/.toolchains/bin:{inside}/.toolchains/node/bin:/usr/local/bin:/usr/bin:/bin
Environment=LD_LIBRARY_PATH={inside}/.toolchains/sqlite/3.51.3/lib
EnvironmentFile={env}
StandardOutput=append:{host_root}/installation/logs/systemd/installation.log
StandardError=append:{host_root}/installation/logs/systemd/installation-error.log
ExecStart={privileged_exec_environment(root)} {inside}/.venv/bin/python -I {inside}/scripts/deploy/installation_worker.py
ExecStartPost={after_tick}
TimeoutStartSec=15min
UMask=0077
'''


TIMER = '''[Unit]
Description=Resume Loopino installation changes and maintain TLS
[Timer]
OnBootSec=30s
OnUnitInactiveSec=30s
Unit=loopino-installation.service
[Install]
WantedBy=timers.target
'''

