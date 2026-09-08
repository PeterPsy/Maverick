"""Private OAuth runtime homes for the Antigravity CLI native adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile

from core.providers.native_structured_cli_transport import NativeStructuredCliError


ANTIGRAVITY_OAUTH_TOKEN_FILENAME = "antigravity-oauth-token"
ANTIGRAVITY_PROFILE_RELATIVE_PATH = Path(".gemini") / "antigravity-cli"
ANTIGRAVITY_OAUTH_TOKEN_MAX_BYTES = 64 * 1024
ANTIGRAVITY_RUNTIME_SETTINGS = {
    "enableTerminalSandbox": True,
    "toolPermission": "request-review",
}


def resolve_antigravity_source_home(
    configured_home: str | Path | None = None,
) -> Path:
    """Resolve the operator-managed Antigravity profile without reading it."""
    configured = str(
        configured_home
        or os.environ.get("MAVERICK_ANTIGRAVITY_HOME")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ANTIGRAVITY_PROFILE_RELATIVE_PATH


def prepare_antigravity_runtime_home(
    runtime_root: Path,
    *,
    source_home: str | Path | None = None,
) -> Path:
    """Copy only OAuth identity into a session-private Antigravity home."""
    runtime = Path(runtime_root).resolve(strict=False)
    home = runtime / "antigravity-home"
    _private_directory(home, runtime)
    for relative in (".config", ".cache", ".local/share", ".local/state"):
        _private_directory(home / relative, runtime)
    profile = home / ANTIGRAVITY_PROFILE_RELATIVE_PATH
    _private_directory(profile, runtime)

    source = resolve_antigravity_source_home(source_home)
    _validate_source_home(source, runtime)
    _copy_private_oauth_token(
        source / ANTIGRAVITY_OAUTH_TOKEN_FILENAME,
        profile / ANTIGRAVITY_OAUTH_TOKEN_FILENAME,
    )
    _write_private_json(profile / "settings.json", ANTIGRAVITY_RUNTIME_SETTINGS)
    return home


def validate_antigravity_oauth_source(
    source_home: str | Path | None = None,
) -> None:
    """Validate the configured OAuth source without exposing its contents."""
    source = resolve_antigravity_source_home(source_home)
    _validate_source_home(source, None)
    descriptor = _open_private_oauth_token(
        source / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
    )
    os.close(descriptor)


def _validate_source_home(source: Path, runtime: Path | None) -> None:
    try:
        details = source.stat(follow_symlinks=False)
        resolved = source.resolve(strict=True)
    except FileNotFoundError as error:
        raise NativeStructuredCliError(
            "antigravity_oauth_credential_missing"
        ) from error
    except (OSError, RuntimeError) as error:
        raise NativeStructuredCliError(
            "antigravity_oauth_credential_unavailable"
        ) from error
    if (
        source.is_symlink()
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or details.st_mode & 0o077
    ):
        raise NativeStructuredCliError("antigravity_oauth_credential_invalid")
    if runtime is not None and resolved.is_relative_to(runtime):
        raise NativeStructuredCliError("antigravity_oauth_credential_invalid")


def _copy_private_oauth_token(source: Path, destination: Path) -> None:
    descriptor = _open_private_oauth_token(source)
    temporary_path: str | None = None
    try:
        before = os.fstat(descriptor)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=".oauth-token-",
            mode="wb",
            delete=False,
        ) as stream:
            temporary_path = stream.name
            os.fchmod(stream.fileno(), 0o600)
            copied = 0
            while True:
                chunk = os.read(descriptor, 8192)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > ANTIGRAVITY_OAUTH_TOKEN_MAX_BYTES:
                    raise NativeStructuredCliError(
                        "antigravity_oauth_credential_invalid"
                    )
                stream.write(chunk)
            if copied != before.st_size:
                raise NativeStructuredCliError(
                    "antigravity_oauth_credential_invalid"
                )
            stream.flush()
            os.fsync(stream.fileno())
        after = os.fstat(descriptor)
        if _source_fence(before) != _source_fence(after):
            raise NativeStructuredCliError("antigravity_oauth_credential_changed")
        os.replace(temporary_path, destination)
        temporary_path = None
        _validate_private_runtime_file(destination)
    finally:
        os.close(descriptor)
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _open_private_oauth_token(source: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except FileNotFoundError as error:
        raise NativeStructuredCliError(
            "antigravity_oauth_credential_missing"
        ) from error
    except OSError as error:
        raise NativeStructuredCliError(
            "antigravity_oauth_credential_unavailable"
        ) from error
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or details.st_mode & 0o077
            or not 0 < details.st_size <= ANTIGRAVITY_OAUTH_TOKEN_MAX_BYTES
        ):
            raise NativeStructuredCliError(
                "antigravity_oauth_credential_invalid"
            )
        path_details = source.stat(follow_symlinks=False)
        if _source_fence(details) != _source_fence(path_details):
            raise NativeStructuredCliError(
                "antigravity_oauth_credential_changed"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _source_fence(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_uid,
        details.st_gid,
        details.st_nlink,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _write_private_json(path: Path, value: object) -> None:
    payload = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=".settings-",
            mode="wb",
            delete=False,
        ) as stream:
            temporary_path = stream.name
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _validate_private_runtime_file(path)
    except NativeStructuredCliError:
        raise
    except OSError as error:
        raise NativeStructuredCliError(
            "antigravity_runtime_home_invalid"
        ) from error
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _validate_private_runtime_file(path: Path) -> None:
    details = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        raise NativeStructuredCliError("antigravity_runtime_home_invalid")
    path.chmod(0o600, follow_symlinks=False)


def _private_directory(path: Path, runtime: Path) -> None:
    resolved_runtime = runtime.resolve(strict=False)
    if path.is_symlink() or not path.resolve(strict=False).is_relative_to(
        resolved_runtime
    ):
        raise NativeStructuredCliError("antigravity_runtime_home_invalid")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    details = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
    ):
        raise NativeStructuredCliError("antigravity_runtime_home_invalid")
    path.chmod(0o700)


__all__ = [
    "ANTIGRAVITY_OAUTH_TOKEN_FILENAME",
    "ANTIGRAVITY_PROFILE_RELATIVE_PATH",
    "ANTIGRAVITY_RUNTIME_SETTINGS",
    "prepare_antigravity_runtime_home",
    "resolve_antigravity_source_home",
    "validate_antigravity_oauth_source",
]
