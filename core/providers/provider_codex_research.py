"""Codex filesystem isolation for web-only Research sessions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable

from core.providers.errors import ProviderLaunchError
from core.providers.codex_app_server_runtime_thread_params import (
    CODEX_RESEARCH_DISABLED_FEATURES,
    CODEX_RESEARCH_ENABLED_FEATURES,
)
from core.providers.codex_device_use_home import device_use_workdir
from core.providers.provider_codex_reasoning import CODEX_DEFAULT_REASONING_EFFORT
from core.runtime.research_runtime import runtime_session_is_research
from core.runtime.runtime_session import RuntimeSessionRecord


CODEX_RESEARCH_AUTH_FILES = (
    "auth.json",
    "version.json",
    ".personality_migration",
    "installation_id",
)
CODEX_RESEARCH_ENV_KEYS = frozenset(
    {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NODE_EXTRA_CA_CERTS",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
)
CODEX_RESEARCH_REVIEWED_VERSIONS = frozenset({"0.153.4"})
_CODEX_VERSION_PATTERN = re.compile(r"^codex-cli (\d+\.\d+\.\d+)$")


@dataclass(frozen=True)
class CodexLaunchScope:
    research: bool
    workdir: Path
    workspace_root: Path
    command_execution_mode: str
    readable_roots: list[str] | None
    writable_roots: list[str] | None
    require_code_mode_host: bool


def codex_research_environment(source: dict[str, str]) -> dict[str, str]:
    """Keep only process essentials before adding the private runtime paths."""
    return {
        key: value
        for key, value in source.items()
        if key in CODEX_RESEARCH_ENV_KEYS and str(value).strip()
    }


@lru_cache(maxsize=8)
def codex_research_runtime_version(command: str) -> str | None:
    """Return an exact reviewed Codex version, otherwise fail closed."""
    try:
        completed = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    first_line = (completed.stdout or completed.stderr).strip().splitlines()
    match = _CODEX_VERSION_PATTERN.fullmatch(first_line[0]) if first_line else None
    version = match.group(1) if match else None
    return version if version in CODEX_RESEARCH_REVIEWED_VERSIONS else None


def validate_codex_research_initialize(
    result: object,
    *,
    expected_home: str,
) -> None:
    """Attest that the isolated process accepted its private Codex home."""
    payload = result if isinstance(result, dict) else {}
    reported_home = str(payload.get("codexHome") or "").strip()
    if not reported_home or Path(reported_home).resolve() != Path(expected_home).resolve():
        raise ProviderLaunchError(
            "codex_research_private_home_unverified",
            reason_code="research_runtime_unavailable",
        )


def codex_launch_scope(session: RuntimeSessionRecord) -> CodexLaunchScope:
    """Resolve the ordinary workspace or isolated Research process boundary."""
    runtime_root = Path(session.runtime_root)
    workspace_root = Path(session.workspace_root)
    research = runtime_session_is_research(session)
    workdir = (
        runtime_root / "research-workdir"
        if research
        else device_use_workdir(session, runtime_root)
    )
    workdir.mkdir(parents=True, exist_ok=True)
    return CodexLaunchScope(
        research=research,
        workdir=workdir,
        workspace_root=workdir if research else workspace_root,
        command_execution_mode="sandbox" if research else session.effective_mode,
        readable_roots=[str(workdir), str(runtime_root)] if research else None,
        writable_roots=[str(runtime_root)] if research else None,
        require_code_mode_host=(
            research or getattr(session, "device_use_binding", None) is not None
        ),
    )


def prepare_codex_research_runtime_bin(
    runtime_root: Path,
    *,
    reset_path: Callable[[Path], None],
) -> Path:
    """Install only the launcher needed for Codex's native web-search host."""
    runtime_bin = runtime_root / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    for child in tuple(runtime_bin.iterdir()):
        reset_path(child)
    sandbox_launcher = runtime_bin / "workspace_sandbox.py"
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "runtime" / "workspace_sandbox.py",
        sandbox_launcher,
    )
    sandbox_launcher.chmod(0o755)
    return runtime_bin


def prepare_codex_research_runtime_home(
    runtime_home: Path,
    *,
    reset_path: Callable[[Path], None],
    default_model_id: str,
    model_id: str | None,
    model_reasoning_effort: str | None,
) -> None:
    """Write an auth-only home with every non-web model surface disabled."""
    for name in (
        "AGENTS.md",
        "cache",
        "hooks",
        "memories",
        "plugins",
        "rules",
        "skills",
        ".tmp",
    ):
        reset_path(runtime_home / name)
    selected_model = str(model_id or "").strip() or default_model_id
    selected_reasoning = (
        str(model_reasoning_effort or "").strip()
        or CODEX_DEFAULT_REASONING_EFFORT
    )
    lines = [
        f'model = "{selected_model}"',
        f'model_reasoning_effort = "{selected_reasoning}"',
        'web_search = "live"',
        "project_doc_max_bytes = 0",
        "include_permissions_instructions = false",
        "include_apps_instructions = false",
        "include_collaboration_mode_instructions = false",
        "include_environment_context = false",
        "",
        "[mcp_servers]",
        "",
        "[features]",
        *(f"{feature} = false" for feature in CODEX_RESEARCH_DISABLED_FEATURES),
        *(f"{feature} = true" for feature in CODEX_RESEARCH_ENABLED_FEATURES),
        "",
        "[skills]",
        "bundled = { enabled = false }",
        "include_instructions = false",
        "",
        "[tools.experimental_request_user_input]",
        "enabled = false",
        "",
        "[tools.update_plan]",
        "enabled = false",
    ]
    (runtime_home / "config.toml").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


class CodexResearchRuntimeMixin:
    """Intercept Codex home preparation only for isolated Research sessions."""

    def research_runtime_available(self, _binding: object = None) -> bool:
        command = self._runtime_command(self.codex_command)
        return codex_research_runtime_version(command) is not None

    def _prepare_runtime_home(
        self,
        session: RuntimeSessionRecord,
        *,
        runtime_bin: Path | None = None,
        shell_path: str | None = None,
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
    ) -> Path:
        if not runtime_session_is_research(session):
            return super()._prepare_runtime_home(
                session,
                runtime_bin=runtime_bin,
                shell_path=shell_path,
                model_id=model_id,
                model_reasoning_effort=model_reasoning_effort,
            )
        runtime_home = self._runtime_home(session)
        runtime_home.mkdir(parents=True, exist_ok=True)
        source_home = self._source_codex_home()
        if self._same_path(runtime_home, source_home):
            raise ProviderLaunchError("Codex Research requires a private runtime home.")
        self._remove_disabled_runtime_material(runtime_home)
        for filename in CODEX_RESEARCH_AUTH_FILES:
            self._copy_file_if_present(
                source_home / filename,
                runtime_home / filename,
            )
        prepare_codex_research_runtime_home(
            runtime_home,
            reset_path=self._reset_path,
            default_model_id=self.default_model_id(),
            model_id=model_id,
            model_reasoning_effort=model_reasoning_effort,
        )
        return runtime_home

    def _prepare_runtime_bin(
        self,
        session: RuntimeSessionRecord,
        *,
        host_command: str | None = None,
    ) -> Path:
        if not runtime_session_is_research(session):
            return super()._prepare_runtime_bin(
                session,
                host_command=host_command,
            )
        return prepare_codex_research_runtime_bin(
            Path(session.runtime_root),
            reset_path=self._reset_path,
        )


__all__ = [
    "CodexResearchRuntimeMixin",
    "codex_research_environment",
    "codex_research_runtime_version",
    "codex_launch_scope",
    "prepare_codex_research_runtime_bin",
    "prepare_codex_research_runtime_home",
    "validate_codex_research_initialize",
]
