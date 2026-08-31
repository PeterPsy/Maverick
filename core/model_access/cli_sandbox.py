"""Path validation and outer sandbox construction for native Codex."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time
from typing import Iterable
from uuid import uuid4

from core.model_access.catalog import resolve_codex_source_home
from core.model_access.cancellation import CancellationSignal, raise_if_cancelled
from core.model_access.models import ModelAccessReadOnlyMount, ModelAccessScope


_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{7,127}$")
_SAFE_CONNECTION_PROBE_CWD = re.compile(r"^/tmp/od-conn-test-[A-Za-z0-9_-]{1,96}$")
_SAFE_ARTIFACT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_CONFIG = (
    re.compile(r'^model_reasoning_effort="(?:none|minimal|low|medium|high|xhigh|max)"$'),
    re.compile(r'^sandbox_mode="(?:workspace-write|danger-full-access)"$'),
)
_OPENDESIGN_SHELL_ENVIRONMENT_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "OD_BIN",
    "OD_HYPERFRAMES_BIN",
    "OD_NODE_BIN",
    "OD_DAEMON_URL",
    "OD_TOOL_TOKEN",
    "OD_DATA_DIR",
    "OD_PROJECT_ID",
    "OD_PROJECT_DIR",
    "OD_TASK_INPUT_DIR",
)
_SAFE_STATIC_CONFIG = frozenset(
    {
        "allow_login_shell=false",
        'shell_environment_policy.inherit="all"',
        "shell_environment_policy.ignore_default_excludes=true",
        "shell_environment_policy.include_only=["
        + ",".join(f'"{key}"' for key in _OPENDESIGN_SHELL_ENVIRONMENT_KEYS)
        + "]",
    }
)


@dataclass(frozen=True)
class ValidatedCodexInvocation:
    """A translated argv plus the exact read-only directories it needs."""

    argv: tuple[str, ...]
    read_only_mounts: tuple[ModelAccessReadOnlyMount, ...]


def validated_codex_invocation(
    argv: tuple[str, ...],
    *,
    data_root: Path,
    sidecar_cwd: str,
    allow_connection_probe: bool = False,
    read_only_mounts: Iterable[ModelAccessReadOnlyMount] = (),
) -> ValidatedCodexInvocation:
    """Allow only the native OpenDesign Codex adapter grammar."""
    if argv in {("--version",), ("debug", "models"), ("login", "status")}:
        return ValidatedCodexInvocation(argv=argv, read_only_mounts=())
    if not argv or argv[0] != "exec" or len(argv) > 96:
        raise ValueError("Codex invocation is not an approved native adapter command")
    authorized_read_only_mounts = validate_model_access_read_only_mounts(
        read_only_mounts
    )
    output: list[str] = []
    requested_read_only_mounts: list[ModelAccessReadOnlyMount] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if not argument or "\x00" in argument:
            raise ValueError("Codex argument is invalid")
        if argument in {"exec", "resume", "--json", "--skip-git-repo-check", "plugins"}:
            output.append(argument)
            index += 1
            continue
        if argument in {"--sandbox", "--disable"}:
            if index + 1 >= len(argv):
                raise ValueError("Codex option is incomplete")
            value = argv[index + 1]
            allowed = {"workspace-write", "danger-full-access"} if argument == "--sandbox" else {"plugins"}
            if value not in allowed:
                raise ValueError("Codex option is not approved")
            output.extend((argument, value))
            index += 2
            continue
        if argument == "--model":
            if index + 1 >= len(argv) or not _SAFE_MODEL_ID.fullmatch(argv[index + 1]):
                raise ValueError("Codex model id is invalid")
            output.extend((argument, argv[index + 1]))
            index += 2
            continue
        if argument == "-c":
            if index + 1 >= len(argv):
                raise ValueError("Codex config option is incomplete")
            value = argv[index + 1]
            if (
                value != "sandbox_workspace_write.network_access=true"
                and value not in _SAFE_STATIC_CONFIG
                and not any(pattern.fullmatch(value) for pattern in _SAFE_CONFIG)
            ):
                raise ValueError("Codex config option is not approved")
            output.extend((argument, value))
            index += 2
            continue
        if argument in {"-C", "--add-dir"}:
            if index + 1 >= len(argv):
                raise ValueError("Codex path option is incomplete")
            raw_path = argv[index + 1]
            if (
                argument == "-C"
                and allow_connection_probe
                and raw_path == sidecar_cwd
                and is_opendesign_connection_probe(argv, sidecar_cwd)
            ):
                inner = "/workspace"
            elif argument == "--add-dir":
                _host, inner, requested_mount = map_codex_add_directory(
                    data_root,
                    authorized_read_only_mounts,
                    raw_path,
                )
                if requested_mount is not None:
                    requested_read_only_mounts.append(requested_mount)
            else:
                _host, inner = map_sidecar_path(data_root, raw_path)
            output.extend((argument, inner))
            index += 2
            continue
        if index == len(argv) - 1 and _SAFE_SESSION_ID.fullmatch(argument):
            output.append(argument)
            index += 1
            continue
        raise ValueError("Codex argument is not approved")
    if "-C" in argv and sidecar_cwd not in argv:
        raise ValueError("Codex working directory differs from the native adapter cwd")
    return ValidatedCodexInvocation(
        argv=tuple(output),
        read_only_mounts=_minimal_read_only_mounts(requested_read_only_mounts),
    )


def validated_codex_argv(
    argv: tuple[str, ...],
    *,
    data_root: Path,
    sidecar_cwd: str,
    allow_connection_probe: bool = False,
    read_only_mounts: Iterable[ModelAccessReadOnlyMount] = (),
) -> tuple[str, ...]:
    """Return only the translated argv for validation-only callers."""
    return validated_codex_invocation(
        argv,
        data_root=data_root,
        sidecar_cwd=sidecar_cwd,
        allow_connection_probe=allow_connection_probe,
        read_only_mounts=read_only_mounts,
    ).argv


def is_opendesign_connection_probe(argv: tuple[str, ...], sidecar_cwd: str) -> bool:
    """Recognize only the official adapter's isolated connection smoke test."""
    if not _SAFE_CONNECTION_PROBE_CWD.fullmatch(sidecar_cwd):
        return False
    if len(argv) < 5 or argv[:3] != ("exec", "--json", "--skip-git-repo-check"):
        return False
    if "resume" in argv or "--add-dir" in argv or argv.count("-C") != 1:
        return False
    index = argv.index("-C")
    return index + 1 < len(argv) and argv[index + 1] == sidecar_cwd


def map_sidecar_path(data_root: Path, raw: str) -> tuple[Path, str]:
    """Map a sidecar `/data` path into the dedicated `/workspace` mount."""
    sidecar_path = PurePosixPath(raw)
    if not sidecar_path.is_absolute() or sidecar_path.parts[1:2] != ("data",):
        raise ValueError("CLI path must stay in app data")
    relative = PurePosixPath(*sidecar_path.parts[2:])
    if ".." in relative.parts:
        raise ValueError("CLI path must stay in app data")
    root = Path(data_root).resolve(strict=True)
    candidate = root.joinpath(*relative.parts).resolve(strict=True)
    if candidate != root and root not in candidate.parents:
        raise ValueError("CLI path escapes app data")
    return candidate, PurePosixPath("/workspace").joinpath(*relative.parts).as_posix()


def validate_model_access_read_only_mounts(
    mounts: Iterable[ModelAccessReadOnlyMount],
) -> tuple[ModelAccessReadOnlyMount, ...]:
    """Normalize only protected platform artifact namespace roots."""
    normalized: list[ModelAccessReadOnlyMount] = []
    seen_sources: set[Path] = set()
    seen_targets: set[PurePosixPath] = set()
    for mount in mounts:
        source = Path(mount.source)
        try:
            metadata = source.lstat()
            resolved_source = source.resolve(strict=True)
        except OSError as error:
            raise ValueError("Model-access read-only artifact is unavailable") from error
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o022
        ):
            raise PermissionError("Model-access read-only artifact is unsafe")
        target = PurePosixPath(Path(mount.target).as_posix())
        if (
            not target.is_absolute()
            or len(target.parts) != 3
            or target.parts[1] != "artifacts"
            or not _SAFE_ARTIFACT_ID.fullmatch(target.parts[2])
            or resolved_source.name != target.parts[2]
        ):
            raise ValueError("Model-access read-only artifact target is invalid")
        if resolved_source in seen_sources or target in seen_targets:
            raise ValueError("Model-access read-only artifact mount is duplicated")
        seen_sources.add(resolved_source)
        seen_targets.add(target)
        normalized.append(
            ModelAccessReadOnlyMount(
                source=resolved_source,
                target=Path(target.as_posix()),
            )
        )
    return tuple(normalized)


def map_codex_add_directory(
    data_root: Path,
    read_only_mounts: tuple[ModelAccessReadOnlyMount, ...],
    raw: str,
) -> tuple[Path, str, ModelAccessReadOnlyMount | None]:
    """Map one writable-data or declared read-only Codex add-directory."""
    sidecar_path = PurePosixPath(raw)
    if sidecar_path.is_absolute() and sidecar_path.parts[1:2] == ("data",):
        host, inner = map_sidecar_path(data_root, raw)
        return host, inner, None
    host, inner = map_sidecar_read_only_path(read_only_mounts, raw)
    return host, inner, ModelAccessReadOnlyMount(source=host, target=Path(inner))


def map_sidecar_read_only_path(
    mounts: tuple[ModelAccessReadOnlyMount, ...],
    raw: str,
) -> tuple[Path, str]:
    """Resolve a sidecar artifact path beneath one declared namespace."""
    sidecar_path = PurePosixPath(raw)
    if not sidecar_path.is_absolute() or ".." in sidecar_path.parts:
        raise ValueError("CLI path must stay in a declared read-only artifact")
    for mount in mounts:
        target = PurePosixPath(mount.target.as_posix())
        try:
            relative = sidecar_path.relative_to(target)
        except ValueError:
            continue
        root = mount.source.resolve(strict=True)
        try:
            candidate = root.joinpath(*relative.parts).resolve(strict=True)
        except OSError as error:
            raise ValueError("CLI read-only artifact path is unavailable") from error
        if candidate != root and root not in candidate.parents:
            raise ValueError("CLI path escapes declared read-only artifact")
        if not candidate.is_dir():
            raise ValueError("CLI read-only artifact path must be a directory")
        return candidate, sidecar_path.as_posix()
    raise ValueError("CLI path must stay in a declared read-only artifact")


def _minimal_read_only_mounts(
    mounts: Iterable[ModelAccessReadOnlyMount],
) -> tuple[ModelAccessReadOnlyMount, ...]:
    minimal: list[ModelAccessReadOnlyMount] = []
    for mount in mounts:
        target = PurePosixPath(mount.target.as_posix())
        if any(target.is_relative_to(existing.target.as_posix()) for existing in minimal):
            continue
        minimal = [
            existing
            for existing in minimal
            if not PurePosixPath(existing.target.as_posix()).is_relative_to(target)
        ]
        minimal.append(mount)
    return tuple(minimal)


def prepare_codex_home(
    repository_root: Path,
    scope: ModelAccessScope,
    *,
    cancellation: CancellationSignal | None = None,
) -> Path:
    """Create a technical CLI home containing auth only, never runtime state."""
    target = (
        repository_root
        / "tmp"
        / "model-access"
        / "state"
        / scope.workspace_id
        / scope.app_id
        / "codex-home"
    )
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _codex_home_lock(
        target.parent / ".codex-home.lock",
        cancellation=cancellation,
    ):
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.chmod(0o700)
        source_auth = resolve_codex_source_home() / "auth.json"
        if not source_auth.is_file():
            raise FileNotFoundError("Codex authentication is unavailable")
        _atomic_private_copy(source_auth, target / "auth.json")
        _atomic_private_write(
            target / "config.toml",
            b'[projects."/workspace"]\ntrust_level = "trusted"\n',
        )
    return target.resolve(strict=True)


@contextmanager
def codex_home_lock(
    cli_home: Path,
    *,
    cancellation: CancellationSignal | None = None,
):
    """Serialize a complete Codex invocation that shares mutable CLI home state."""
    home = Path(cli_home).resolve(strict=True)
    metadata = home.stat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise PermissionError("Codex home is unsafe")
    with _codex_home_lock(
        home.parent / ".codex-home.lock",
        cancellation=cancellation,
    ):
        yield


def codex_sandbox_command(
    *,
    executable: Path,
    data_root: Path,
    inner_cwd: str,
    cli_home: Path,
    argv: tuple[str, ...],
    read_only_mounts: tuple[ModelAccessReadOnlyMount, ...] = (),
    authorized_read_only_mounts: tuple[ModelAccessReadOnlyMount, ...] = (),
) -> list[str]:
    """Build the outer capability sandbox around the standalone CLI."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise FileNotFoundError("bubblewrap is unavailable")
    metadata = Path(bwrap).resolve().stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o022:
        raise PermissionError("bubblewrap is not trusted")
    command = [
        str(Path(bwrap).resolve()),
        "--die-with-parent",
        "--unshare-user",
        "--uid",
        "0",
        "--gid",
        "0",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--tmpfs",
        "/",
        "--dir",
        "/workspace",
        "--dir",
        "/codex-home",
        "--dir",
        "/home",
        "--dir",
        "/home/codex",
        "--dir",
        "/etc",
        "--dir",
        "/artifacts",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--bind",
        str(Path(data_root).resolve(strict=True)),
        "/workspace",
        "--bind",
        str(cli_home),
        "/codex-home",
    ]
    created_directories = {PurePosixPath("/artifacts")}
    sandbox_mounts = _validated_sandbox_read_only_mounts(
        read_only_mounts,
        authorized_mounts=validate_model_access_read_only_mounts(
            authorized_read_only_mounts
        ),
    )
    for mount in sandbox_mounts:
        current = PurePosixPath("/")
        for component in PurePosixPath(mount.target.as_posix()).parts[1:]:
            current /= component
            if current not in created_directories:
                command.extend(("--dir", current.as_posix()))
                created_directories.add(current)
    for mount in sandbox_mounts:
        command.extend(
            (
                "--ro-bind",
                mount.source.as_posix(),
                mount.target.as_posix(),
            )
        )
    for path in ("/etc/ssl", "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf"):
        if Path(path).exists():
            command.extend(("--ro-bind", path, path))
    command.extend(
        (
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--chdir",
            inner_cwd,
            "--",
            executable.as_posix(),
            *argv,
        )
    )
    return command


def _validated_sandbox_read_only_mounts(
    mounts: tuple[ModelAccessReadOnlyMount, ...],
    *,
    authorized_mounts: tuple[ModelAccessReadOnlyMount, ...],
) -> tuple[ModelAccessReadOnlyMount, ...]:
    normalized: list[ModelAccessReadOnlyMount] = []
    seen_targets: set[PurePosixPath] = set()
    for mount in mounts:
        try:
            source = Path(mount.source).resolve(strict=True)
        except OSError as error:
            raise ValueError("Codex read-only directory is unavailable") from error
        if not source.is_dir():
            raise ValueError("Codex read-only mount source must be a directory")
        target = PurePosixPath(Path(mount.target).as_posix())
        if (
            not target.is_absolute()
            or len(target.parts) < 3
            or target.parts[1] != "artifacts"
            or not _SAFE_ARTIFACT_ID.fullmatch(target.parts[2])
            or ".." in target.parts
            or target in seen_targets
        ):
            raise ValueError("Codex read-only mount target is invalid")
        if not _read_only_mount_is_authorized(
            source=source,
            target=target,
            authorized_mounts=authorized_mounts,
        ):
            raise PermissionError("Codex read-only mount is not lease-authorized")
        seen_targets.add(target)
        normalized.append(
            ModelAccessReadOnlyMount(source=source, target=Path(target.as_posix()))
        )
    return tuple(normalized)


def _read_only_mount_is_authorized(
    *,
    source: Path,
    target: PurePosixPath,
    authorized_mounts: tuple[ModelAccessReadOnlyMount, ...],
) -> bool:
    for authorized in authorized_mounts:
        authorized_target = PurePosixPath(authorized.target.as_posix())
        try:
            relative = target.relative_to(authorized_target)
            expected_source = authorized.source.joinpath(*relative.parts).resolve(
                strict=True
            )
        except (ValueError, OSError):
            continue
        if (
            expected_source == source
            and (
                expected_source == authorized.source
                or authorized.source in expected_source.parents
            )
        ):
            return True
    return False


def _atomic_private_copy(source: Path, destination: Path) -> None:
    try:
        body = source.read_bytes()
    except OSError as error:
        raise FileNotFoundError("Codex authentication is unavailable") from error
    _atomic_private_write(destination, body)


def _atomic_private_write(destination: Path, body: bytes) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        remaining = memoryview(body)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("private atomic write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, destination)
        destination.chmod(0o600)
        directory = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def _codex_home_lock(
    path: Path,
    *,
    cancellation: CancellationSignal | None = None,
):
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise PermissionError("Codex home lock is unsafe")
        while True:
            if cancellation is not None:
                raise_if_cancelled(cancellation)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if cancellation is None:
                    time.sleep(0.05)
                else:
                    cancellation.wait(0.05)
                continue
            acquired = True
            break
        if cancellation is not None:
            raise_if_cancelled(cancellation)
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
