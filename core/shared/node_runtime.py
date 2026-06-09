"""Node.js runtime version policy for Maverick frontend tooling."""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess

MINIMUM_NODE_VERSION = (24, 11, 0)
MINIMUM_NODE_VERSION_TEXT = ".".join(str(part) for part in MINIMUM_NODE_VERSION)
SUPPORTED_NODE_MAJOR = 24
NODE_ENGINE_RANGE = f">={MINIMUM_NODE_VERSION_TEXT} <25"
NODE_RUNTIME_REQUIREMENT = f"Node.js 24 LTS ({NODE_ENGINE_RANGE})"


@dataclass(frozen=True, order=True)
class NodeVersion:
    major: int
    minor: int
    patch: int

    def format(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_node_version(value: str) -> NodeVersion | None:
    """Parse a `node --version` style string."""
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)\b", value.strip())
    if match is None:
        return None
    return NodeVersion(*(int(part) for part in match.groups()))


def node_version_supported(version: NodeVersion) -> bool:
    return version.major == SUPPORTED_NODE_MAJOR and version >= NodeVersion(*MINIMUM_NODE_VERSION)


def node_runtime_diagnostic(*, node_command: str = "node") -> str | None:
    """Return an actionable diagnostic when the available Node runtime is unsupported."""
    executable = shutil.which(node_command)
    if executable is None:
        return "node not found in PATH"
    completed = subprocess.run(
        [executable, "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return f"node at `{executable}` could not report its version: {detail or 'unknown error'}"
    version = parse_node_version(completed.stdout)
    if version is None:
        return f"node at `{executable}` returned an unrecognized version `{completed.stdout.strip()}`"
    if version.major > SUPPORTED_NODE_MAJOR:
        return (
            f"node {version.format()} at `{executable}` is outside the supported range; "
            f"Maverick requires {NODE_RUNTIME_REQUIREMENT}"
        )
    if not node_version_supported(version):
        return f"node {version.format()} at `{executable}` is too old; Maverick requires {NODE_RUNTIME_REQUIREMENT}"
    return None


def require_supported_node_runtime(*, node_command: str = "node") -> None:
    diagnostic = node_runtime_diagnostic(node_command=node_command)
    if diagnostic is not None:
        raise RuntimeError(diagnostic)
