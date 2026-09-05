"""Content-addressed identity of the actual native executable, not its shim."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
from threading import RLock

from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class NativeRuntimeArtifact:
    sha256: str
    version: str

    @property
    def digest(self) -> str:
        return canonical_digest(self)


# Explicitly reviewed installed release. Discovery cannot approve an update.
CODEX_PACKAGED_RUNTIME_ARTIFACT = NativeRuntimeArtifact(
    "56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da",
    "codex-cli 0.153.4",
)
_CACHE = {}
_LOCK = RLock()


def inspect_native_runtime_artifact(command: str) -> NativeRuntimeArtifact:
    try:
        path = Path(command).resolve(strict=True)
        before = path.stat()
        fence = (str(path), before.st_dev, before.st_ino, before.st_size,
                 before.st_mtime_ns, before.st_ctime_ns, before.st_mode)
        with _LOCK:
            if fence in _CACHE:
                return _CACHE[fence]
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            version = subprocess.run(
                [str(path), "--version"], check=True, capture_output=True, text=True, timeout=3,
            ).stdout.strip()
            after = path.stat()
            final_fence = (str(path), after.st_dev, after.st_ino, after.st_size,
                           after.st_mtime_ns, after.st_ctime_ns, after.st_mode)
            if not version or len(version) > 256 or final_fence != fence:
                raise ValueError("native_runtime_artifact_unstable")
            artifact = NativeRuntimeArtifact(digest, version)
            if len(_CACHE) >= 8:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[fence] = artifact
            return artifact
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise CapabilityCertificateError("native_runtime_artifact_unavailable") from error


__all__ = ["CODEX_PACKAGED_RUNTIME_ARTIFACT", "NativeRuntimeArtifact", "inspect_native_runtime_artifact"]
