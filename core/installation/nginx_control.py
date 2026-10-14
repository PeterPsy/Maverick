"""Validate and reload only the verified running Nginx master."""

import os
from pathlib import Path
import re
import signal
import subprocess


def running_master(proc_root=Path("/proc")) -> tuple[int, str, str]:
    matches = []
    for folder in proc_root.glob("[0-9]*"):
        try:
            command = (folder / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if not command.startswith("nginx: master process /usr/sbin/nginx "):
                continue
            config = re.search(r"(?:^| )-c ([^ ]+)", command)
            config_path = config.group(1) if config else "/etc/nginx/nginx.conf"
            if not config_path.startswith("/"):
                raise ValueError("The running nginx configuration must be absolute")
            # /proc/stat field 22, following the parenthesized process name.
            started = (folder / "stat").read_text().rsplit(") ", 1)[1].split()[19]
            matches.append((int(folder.name), config_path, started))
        except (FileNotFoundError, ProcessLookupError):
            continue
    if len(matches) != 1:
        raise RuntimeError("Exactly one running nginx master is required")
    return matches[0]


def check_nginx(*, runner=subprocess.run, finder=running_master):
    master = finder()
    runner(["/usr/sbin/nginx", "-t", "-c", master[1]], check=True, capture_output=True)
    if finder() != master:
        raise RuntimeError("The nginx master changed during validation")
    return master


def reload_nginx(*, runner=subprocess.run, finder=running_master, sender=os.kill):
    master = check_nginx(runner=runner, finder=finder)
    # This also works in the migrated chroot without a systemd bus or a PID file.
    sender(master[0], signal.SIGHUP)
