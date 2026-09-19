"""Linux read-only runtime closure with a Unix listener and no host network."""
import json
from pathlib import Path
import shutil
import sys
import sysconfig


def command(*, app_root, public_roots, projection_directory, listener_directory, domain):
    bwrap = shutil.which("bwrap")
    interpreter = Path(sys.executable).resolve()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    if not bwrap or sys.platform != "linux" or not str(interpreter).startswith("/usr/bin/") or not str(stdlib).startswith("/usr/lib/"):
        raise RuntimeError("supported_linux_confinement_required")
    args = [bwrap, "--die-with-parent", "--unshare-all", "--cap-drop", "ALL", "--clearenv",
            "--setenv", "PATH", "/usr/bin", "--setenv", "LANG", "C.UTF-8",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "PYTHONNOUSERSITE", "1",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/usr/bin",
            "--ro-bind", str(interpreter), "/usr/bin/python3",
            "--ro-bind", str(stdlib), str(stdlib)]
    # Dynamic loader/library directories, not /usr, /etc, homes, or repository roots.
    for path in (Path("/usr/lib/x86_64-linux-gnu"), Path("/usr/lib/aarch64-linux-gnu"), Path("/usr/lib64")):
        if path.is_dir():
            args += ["--ro-bind", str(path), str(path)]
    args += ["--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
             "--ro-bind", str(app_root / "backend"), "/app/backend",
             "--ro-bind", str(app_root / "public_server"), "/app/public_server",
             "--ro-bind", str(projection_directory), "/state",
             "--bind", str(listener_directory), "/listener", "--dir", "/sites"]
    mounts = {}
    for namespace, root in sorted(public_roots.items()):
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError("unsafe_public_mount")
        target = "/sites/" + namespace
        args += ["--ro-bind", str(root), target]
        mounts[namespace] = target
    args += ["--chdir", "/app", "/usr/bin/python3", "/app/public_server/server.py",
             "--socket", "/listener/public.sock", "--domain", domain,
             "--projection", "/state/mounts.json", "--mounts", json.dumps(mounts, sort_keys=True)]
    return args
