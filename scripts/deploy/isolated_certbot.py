"""Certbot in a private mount namespace with only protected CLI configuration.

Entered only through loopino-certbot (unshare); never edits Certbot internals or
the host's configuration. The private empty mount masks ambient Linux defaults.
"""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.installation.privileged_context import enter_privileged_context
from core.installation.protected_material import protected_directory, require_protected_parents


def prepare_config(root: Path) -> tuple[Path, Path]:
    empty = protected_directory(root / "installation/tls/empty-host-config")
    if any(empty.iterdir()):
        raise ValueError("Ambient Certbot mask must be empty")
    config = root / "installation/tls/certbot/cli.ini"
    protected_directory(config.parent)
    require_protected_parents(config)
    if not config.exists():
        with config.open("x") as stream:
            stream.write("# Loopino root-operator CLI configuration; no ambient defaults.\n")
        config.chmod(0o600)
    metadata = config.lstat()
    if not config.is_file() or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError("Certbot CLI configuration must be root-controlled")
    return empty, config


def main() -> int:
    if os.geteuid() != 0 or not sys.flags.isolated:
        raise PermissionError("Use the isolated root-operator Certbot launcher")
    # A direct call must never mount over the host namespace.
    if Path("/proc/self/ns/mnt").stat().st_ino == Path("/proc/1/ns/mnt").stat().st_ino:
        raise PermissionError("Certbot requires a private mount namespace")
    enter_privileged_context(ROOT)
    empty, config = prepare_config(ROOT)
    args = sys.argv[1:]
    if any(arg == "-c" or arg.startswith("-c=") or arg == "--config" or arg.startswith("--config=")
           or (arg.startswith("-c") and not arg.startswith("--")) for arg in args):
        raise ValueError("Certbot CLI configuration is fixed by the installation")
    subprocess.run(["/usr/bin/mount", "--bind", str(empty), "/etc/letsencrypt"], check=True)
    subprocess.run(["/usr/bin/mount", "-o", "remount,bind,ro", "/etc/letsencrypt"], check=True)
    # The user default remains inside the protected privileged HOME/XDG tree.
    # A second private empty mount suppresses even an unintended local default.
    user_config = protected_directory(Path(os.environ["XDG_CONFIG_HOME"]) / "letsencrypt")
    subprocess.run(["/usr/bin/mount", "--bind", str(empty), str(user_config)], check=True)
    subprocess.run(["/usr/bin/mount", "-o", "remount,bind,ro", str(user_config)], check=True)
    from certbot.main import main as certbot_main
    from core.shared.installation_material import certbot_directory_arguments
    defaults = certbot_directory_arguments(ROOT)
    return certbot_main([*defaults, "--config", str(config), *args]) or 0


if __name__ == "__main__":
    raise SystemExit(main())
