#!/usr/bin/env python3
"""Validate the running nginx configuration and signal its verified master."""

import argparse
import json
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Root privileges are required")
    try:
        if args.test_only:
            check_nginx()
        else:
            reload_nginx()
        print(json.dumps({"status": "validated" if args.test_only else "reloaded"}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "blocked", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
