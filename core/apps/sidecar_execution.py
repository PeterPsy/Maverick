"""Fail-closed launch planning for app-owned confined HTTP sidecars."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys
import sysconfig

from core.apps.errors import AppHostingError
from core.apps.artifact_mounts import ResolvedArtifactMount
from core.apps.models import HttpSidecarSpec


MINIMAL_SIDECAR_ENV = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONNOUSERSITE": "1",
    "TMPDIR": "/tmp",
    "TZ": "UTC",
}
RELAY_PROTOCOL_PREFIX = b"MAVERICK-SIDECAR-RELAY/1 "
_SANDBOX_APP_ROOT = Path("/app")
_SANDBOX_DATA_ROOT = Path("/data")
_SANDBOX_RELAY_SOCKET = Path("/relay/r.sock")
_RUNTIME_READ_ONLY_DIRS = (Path("/etc/ssl"),)


@dataclass
class ConfinedSidecarLaunch:
    """Prepared bubblewrap invocation plus relay identity and cleanup state."""

    command: list[str]
    env: dict[str, str]
    relay_directory: Path
    relay_socket: Path
    relay_capability: str
    secret_fd: int
    passwd_fd: int

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (self.secret_fd, self.passwd_fd)

    def close_parent_fds(self) -> None:
        for attribute in ("secret_fd", "passwd_fd"):
            fd = getattr(self, attribute)
            if fd < 0:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
            setattr(self, attribute, -1)

    def cleanup(self) -> None:
        self.close_parent_fds()
        self.relay_socket.unlink(missing_ok=True)
        try:
            self.relay_directory.rmdir()
        except OSError:
            pass


def sandbox_substitutions(
    *,
    port: int,
    token: str,
    artifact_mounts: tuple[ResolvedArtifactMount, ...] = (),
) -> dict[str, str]:
    """Return the only path/token substitutions exposed inside the sandbox."""
    substitutions = {
        "${service.port}": str(port),
        "${service.token}": token,
        "${app.data_dir}": str(_SANDBOX_DATA_ROOT),
        "${app.source_dir}": str(_SANDBOX_APP_ROOT),
    }
    substitutions.update(
        {f"${{artifact.{mount.artifact_id}}}": mount.target.as_posix() for mount in artifact_mounts}
    )
    return substitutions


def prepare_confined_sidecar_launch(
    *,
    workspace_id: str,
    app_id: str,
    source_root: Path,
    data_root: Path,
    workspace_root: Path,
    sidecar: HttpSidecarSpec,
    port: int,
    env: dict[str, str],
    artifact_mounts: tuple[ResolvedArtifactMount, ...] = (),
) -> ConfinedSidecarLaunch:
    """Build a bubblewrap launch or raise without returning an unsafe fallback."""
    policy = sidecar.process_policy
    limits = policy.limits
    invalid_limits = (
        isinstance(limits.memory_bytes, bool)
        or not isinstance(limits.memory_bytes, int)
        or not 64 * 1024 * 1024 <= limits.memory_bytes <= 64 * 1024 * 1024 * 1024
        or isinstance(limits.open_files, bool)
        or not isinstance(limits.open_files, int)
        or not 64 <= limits.open_files <= 65536
        or isinstance(limits.request_concurrency, bool)
        or not isinstance(limits.request_concurrency, int)
        or not 1 <= limits.request_concurrency <= 1024
    )
    if invalid_limits or (
        policy.inherit_host_env
        or policy.sandbox != "required"
        or not policy.bundle_read_only
        or not policy.workspace_data_write
        or policy.network != "isolated"
        or policy.transport != "unix_relay"
        or policy.outbound
    ):
        raise AppHostingError("HTTP sidecar process policy is not fail-closed.")
    bwrap = _trusted_bubblewrap_binary()
    _validate_sandbox_command(sidecar.command)

    source = _require_real_directory(source_root, label="sidecar source root")
    workspace = _require_real_directory(workspace_root, label="workspace root")
    runtime_mount_arguments = _runtime_mount_arguments(sidecar)
    app_data_path = workspace / "data" / app_id
    lexical_data = Path(os.path.abspath(data_root))
    try:
        lexical_data.relative_to(app_data_path)
    except ValueError as error:
        raise AppHostingError("Sidecar data root must stay within its app-owned workspace data root.") from error
    _reject_symlink_components(app_data_path, anchor=workspace, label="app-owned workspace data root")
    _reject_symlink_components(lexical_data, anchor=workspace, label="sidecar data root")
    app_data_root = app_data_path.resolve()
    data = lexical_data.resolve()
    if data != app_data_root and app_data_root not in data.parents:
        raise AppHostingError("Sidecar data root must stay within its app-owned workspace data root.")
    _ensure_real_directory(data, label="sidecar data root", create=True)
    _reject_symlink_components(lexical_data, anchor=workspace, label="sidecar data root")

    workdir = (_SANDBOX_APP_ROOT / sidecar.working_directory).as_posix()
    relay_directory = _create_relay_directory(
        workspace=workspace,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar.service_id,
        data_root=data,
    )
    relay_socket = relay_directory / "r.sock"
    capability = secrets.token_urlsafe(32)
    secret_fd = -1
    passwd_fd = -1
    try:
        secret_fd = _pipe_with_payload(capability.encode("ascii") + b"\n")
        passwd_fd = _pipe_with_payload(b"maverick-sidecar:x:0:0::/tmp/home:/usr/sbin/nologin\n")
        relay_source = Path(__file__).with_name("sidecar_relay.py").resolve()
        command = [
            bwrap,
            "--die-with-parent",
            "--unshare-user",
            "--uid",
            "0",
            "--gid",
            "0",
            "--unshare-pid",
            "--unshare-net",
            "--unshare-ipc",
            "--unshare-uts",
            "--tmpfs",
            "/",
        ]
        for directory in (
            "/usr",
            "/usr/bin",
            "/usr/lib",
            "/usr/lib64",
            "/usr/local",
            "/usr/local/bin",
            "/usr/local/lib",
            "/etc",
            "/etc/ssl",
            "/app",
            "/artifacts",
            "/data",
            "/relay",
            "/maverick",
            "/proc",
            "/dev",
            "/tmp",
        ):
            command.extend(["--dir", directory])
        command.extend(runtime_mount_arguments)
        for artifact_mount in artifact_mounts:
            if artifact_mount.target != Path(f"/artifacts/{artifact_mount.artifact_id}"):
                raise AppHostingError("HTTP sidecar artifact mount target is not platform-owned.")
            command.extend(
                [
                    "--dir",
                    artifact_mount.target.as_posix(),
                    "--ro-bind",
                    artifact_mount.source.as_posix(),
                    artifact_mount.target.as_posix(),
                ]
            )
        command.extend(
            [
                "--file",
                str(passwd_fd),
                "/etc/passwd",
                "--ro-bind",
                str(source),
                "/app",
                "--bind",
                str(data),
                "/data",
                "--bind",
                str(relay_directory),
                "/relay",
                "--ro-bind",
                str(relay_source),
                "/maverick/sidecar_relay.py",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--dir",
                "/tmp/home",
                "--remount-ro",
                "/",
                "--chdir",
                workdir,
                "/usr/bin/python3",
                "/maverick/sidecar_relay.py",
                "--relay-socket",
                str(_SANDBOX_RELAY_SOCKET),
                "--secret-fd",
                str(secret_fd),
                "--target-host",
                sidecar.bind.host,
                "--target-port",
                str(port),
                "--workdir",
                workdir,
                "--memory-bytes",
                str(policy.limits.memory_bytes),
                "--open-files",
                str(policy.limits.open_files),
                "--request-concurrency",
                str(policy.limits.request_concurrency),
                "--",
                *sidecar.command,
            ]
        )
    except Exception:
        for fd in (secret_fd, passwd_fd):
            if fd >= 0:
                os.close(fd)
        relay_socket.unlink(missing_ok=True)
        try:
            relay_directory.rmdir()
        except OSError:
            pass
        raise
    return ConfinedSidecarLaunch(
        command=command,
        env=dict(env),
        relay_directory=relay_directory,
        relay_socket=relay_socket,
        relay_capability=capability,
        secret_fd=secret_fd,
        passwd_fd=passwd_fd,
    )


def relay_preamble(capability: str) -> bytes:
    """Build the authenticated preamble stripped by the private relay."""
    return RELAY_PROTOCOL_PREFIX + capability.encode("ascii") + b"\n"


def _pipe_with_payload(payload: bytes) -> int:
    read_fd, write_fd = os.pipe()
    try:
        written = os.write(write_fd, payload)
        if written != len(payload):
            raise OSError("short write while preparing sidecar launch")
    except Exception:
        os.close(read_fd)
        raise
    finally:
        os.close(write_fd)
    return read_fd


def _trusted_bubblewrap_binary() -> str:
    candidate = shutil.which("bwrap")
    if not candidate:
        raise AppHostingError("bubblewrap is required for sandbox-required HTTP sidecars; no fallback is available.")
    path = Path(candidate).resolve()
    try:
        metadata = path.stat()
    except OSError as error:
        raise AppHostingError("The bubblewrap executable is unavailable.") from error
    trusted_parents = {Path("/usr/bin"), Path("/usr/local/bin")}
    if (
        path.parent not in trusted_parents
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise AppHostingError("bubblewrap must be a root-owned, non-writable executable in a trusted system bin directory.")
    return str(path)


def _runtime_mount_arguments(sidecar: HttpSidecarSpec) -> list[str]:
    python_binary = Path(sys.executable).resolve()
    python_stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    multiarch = str(sysconfig.get_config_var("MULTIARCH") or "").strip()
    shared_libraries = Path("/usr/lib") / multiarch
    required_paths = (python_binary, python_stdlib, shared_libraries, Path("/usr/lib64"))
    if any(not path.exists() for path in required_paths):
        raise AppHostingError("The minimal Python sidecar runtime closure is unavailable.")
    arguments = [
        "--ro-bind",
        str(python_binary),
        f"/usr/bin/{python_binary.name}",
        "--symlink",
        python_binary.name,
        "/usr/bin/python3",
        "--ro-bind",
        str(python_stdlib),
        f"/usr/lib/{python_stdlib.name}",
        "--ro-bind",
        str(shared_libraries),
        str(shared_libraries),
        "--ro-bind",
        "/usr/lib64",
        "/usr/lib64",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--symlink",
        "usr/bin",
        "/bin",
    ]
    if sidecar.runtime == "node" or sidecar.package_manager is not None:
        node_binary, node_root = _trusted_node_runtime()
        arguments.extend(
            [
                "--ro-bind",
                str(node_root),
                str(node_root),
                "--symlink",
                str(node_binary),
                "/usr/local/bin/node",
            ]
        )
    for source in _RUNTIME_READ_ONLY_DIRS:
        if source.exists():
            arguments.extend(["--ro-bind", source.as_posix(), source.as_posix()])
    return arguments


def _trusted_node_runtime() -> tuple[Path, Path]:
    candidate = shutil.which("node")
    if not candidate:
        raise AppHostingError("The minimal Node sidecar runtime closure is unavailable.")
    node_binary = Path(candidate).resolve()
    node_root = node_binary.parent.parent
    trusted_roots = (Path("/usr/local/lib"), Path("/usr/lib"))
    try:
        binary_metadata = node_binary.stat()
        root_metadata = node_root.stat()
    except OSError as error:
        raise AppHostingError("The minimal Node sidecar runtime closure is unavailable.") from error
    inside_trusted_root = any(node_root == root or root in node_root.parents for root in trusted_roots)
    if (
        not inside_trusted_root
        or node_binary.name != "node"
        or node_binary.parent.name != "bin"
        or not stat.S_ISREG(binary_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or not binary_metadata.st_mode & stat.S_IXUSR
        or binary_metadata.st_mode & 0o022
        or root_metadata.st_mode & 0o022
    ):
        raise AppHostingError("The minimal Node sidecar runtime closure is not in a trusted read-only system location.")
    return node_binary, node_root


def _validate_sandbox_command(command: list[str]) -> None:
    if not command:
        raise AppHostingError("HTTP sidecar command is empty.")
    executable = Path(command[0])
    if executable.is_absolute() or ".." in executable.parts:
        raise AppHostingError("Sandbox-required sidecar commands cannot select an absolute or parent host path.")


def _require_real_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise AppHostingError(f"{label.capitalize()} must be an existing real directory.")
    return path.resolve()


def _ensure_real_directory(path: Path, *, label: str, create: bool) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return _require_real_directory(path, label=label)


def _reject_symlink_components(path: Path, *, anchor: Path, label: str) -> None:
    try:
        relative = path.relative_to(anchor)
    except ValueError as error:
        raise AppHostingError(f"{label.capitalize()} must stay within the workspace root.") from error
    current = anchor
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise AppHostingError(f"{label.capitalize()} cannot contain symlink components.")


def _create_relay_directory(
    *,
    workspace: Path,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    data_root: Path,
) -> Path:
    runtime_root = workspace / "runtime"
    _ensure_real_directory(runtime_root, label="workspace runtime root", create=True)
    relay_root = runtime_root / "sc"
    _ensure_real_directory(relay_root, label="sidecar relay root", create=True)
    os.chmod(relay_root, stat.S_IRWXU)
    identity = "\0".join((workspace_id, app_id, sidecar_id, str(data_root))).encode("utf-8")
    identity_hash = hashlib.sha256(identity).hexdigest()[:12]
    relay_directory = relay_root / f"{identity_hash}-{secrets.token_hex(4)}"
    relay_directory.mkdir(mode=0o700)
    if len(os.fsencode(relay_directory / "r.sock")) >= 104:
        relay_directory.rmdir()
        raise AppHostingError("Sidecar relay socket path exceeds the platform Unix-socket limit.")
    return relay_directory
