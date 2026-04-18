"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from core.providers.errors import ProviderLaunchError
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.runtime.runtime_session import RuntimeSessionRecord

if TYPE_CHECKING:
    from core.skills.models import SkillDefinition, SkillMaterialization


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def build_codex_definition(now: datetime | None = None) -> ProviderDefinition:
    """Build the canonical provider definition for the local Codex backend."""
    timestamp = now or utcnow()
    return ProviderDefinition(
        provider_id="codex",
        label="Codex",
        description="Local Codex runtime backend for interactive agent execution.",
        kind="runtime_backend",
        status="active",
        capabilities=ProviderCapabilitySet(
            supports_interactive_runtime=True,
            supports_streaming=True,
            supports_tools=True,
            supports_mcp=True,
            supports_skills=True,
            supports_filesystem_access=True,
            supports_remote_execution=False,
            supports_api_key_auth=False,
            supports_local_binary=True,
        ),
        default_model_family="codex",
        requires_credentials=False,
        supported_execution_modes=["sandbox", "full-access"],
        created_at=timestamp,
        updated_at=timestamp,
    )


class CodexProviderAdapter:
    """Construct launch specs for the local Codex runtime backend."""

    def __init__(
        self,
        *,
        codex_command: str = "codex",
        sandbox_enable_flag: str = "use_legacy_landlock",
        server_args: list[str] | None = None,
    ) -> None:
        self.codex_command = str(codex_command or "").strip() or "codex"
        self.sandbox_enable_flag = str(sandbox_enable_flag or "").strip() or "use_legacy_landlock"
        self.server_args = list(server_args or ["app-server", "--listen", "stdio://"])

    def provider_definition(self) -> ProviderDefinition:
        """Return the canonical definition exposed by this adapter."""
        return build_codex_definition()

    def validate_backend(self) -> None:
        """Ensure the configured Codex binary is available locally."""
        command = self.codex_command
        if os.sep in command:
            resolved = Path(command).expanduser()
            if not resolved.is_file():
                raise ProviderLaunchError(f"Configured Codex binary `{resolved}` does not exist.")
            return
        if shutil.which(command) is None:
            raise ProviderLaunchError(f"Codex binary `{command}` is not available on PATH.")

    def build_launch_spec(self, session: RuntimeSessionRecord) -> RuntimeBackendLaunchSpec:
        """Build one runtime launch spec for the local Codex backend."""
        self.validate_backend()
        workdir = Path(session.workdir)
        workspace_root = Path(session.workspace_root)
        runtime_root = Path(session.runtime_root)
        runtime_home = self._runtime_home(session)
        runtime_home.mkdir(parents=True, exist_ok=True)
        env = self._build_subprocess_env(
            workdir=workdir,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            runtime_home=runtime_home,
            execution_mode=session.effective_mode,
        )
        return RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=self._build_command(execution_mode=session.effective_mode),
            env_overrides=env,
            working_directory=str(workdir),
            execution_mode=session.effective_mode,
            writable_roots=self._writable_roots(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                execution_mode=session.effective_mode,
            ),
        )

    def prepare_runtime_skills(
        self,
        session: RuntimeSessionRecord,
        skills: list["SkillDefinition"],
    ) -> list["SkillMaterialization"]:
        """Install skills into the Codex runtime home using provider-specific layout rules."""
        from core.skills.models import SkillMaterialization

        runtime_home = self._runtime_home(session)
        skills_root = runtime_home / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        materializations: list[SkillMaterialization] = []
        for skill in skills:
            source_root = Path(skill.source_root).resolve()
            target_root = skills_root / skill.skill_id
            if target_root.exists() or target_root.is_symlink():
                if target_root.is_symlink() or target_root.is_file():
                    target_root.unlink()
                else:
                    shutil.rmtree(target_root)
            target_root.symlink_to(source_root, target_is_directory=True)
            materializations.append(
                SkillMaterialization(
                    provider_id="codex",
                    skill_id=skill.skill_id,
                    source_root=str(source_root),
                    target_root=str(target_root),
                    strategy="symlink",
                )
            )
        return materializations

    def _build_command(self, *, execution_mode: str) -> list[str]:
        command = [self.codex_command]
        if execution_mode == "sandbox":
            command.extend(["--enable", self.sandbox_enable_flag])
        command.extend(self.server_args)
        return command

    def _build_subprocess_env(
        self,
        *,
        workdir: Path,
        workspace_root: Path,
        runtime_root: Path,
        runtime_home: Path,
        execution_mode: str,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(base_env or os.environ)
        path_entries = [entry for entry in str(env.get("PATH") or "").split(os.pathsep) if entry]
        prepend_entries: list[str] = []

        if os.sep in self.codex_command:
            configured = Path(self.codex_command).expanduser()
            prepend_entries.append(str(configured.parent))
        else:
            resolved = shutil.which(self.codex_command, path=os.pathsep.join(path_entries)) or shutil.which(self.codex_command)
            if resolved:
                prepend_entries.append(str(Path(resolved).resolve().parent))

        resolved_node = shutil.which("node", path=os.pathsep.join(path_entries)) or shutil.which("node")
        if resolved_node:
            prepend_entries.append(str(Path(resolved_node).resolve().parent))

        merged_path: list[str] = []
        seen: set[str] = set()
        for entry in [*prepend_entries, *path_entries]:
            normalized = str(entry or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged_path.append(normalized)
        if merged_path:
            env["PATH"] = os.pathsep.join(merged_path)

        env["CODEX_HOME"] = str(runtime_home)
        env["MAVERICK_WORKSPACE_ROOT"] = str(workspace_root)
        env["MAVERICK_RUNTIME_ROOT"] = str(runtime_root)
        if execution_mode == "sandbox":
            sandbox_tmpdir = runtime_root / ".tmp" / "codex-sandbox"
            sandbox_tmpdir.mkdir(parents=True, exist_ok=True)
            env["TMPDIR"] = str(sandbox_tmpdir)
            env["TMP"] = str(sandbox_tmpdir)
            env["TEMP"] = str(sandbox_tmpdir)
        return env

    def _runtime_home(self, session: RuntimeSessionRecord) -> Path:
        return Path(session.runtime_root) / "codex-home"

    def _writable_roots(self, *, workspace_root: Path, runtime_root: Path, execution_mode: str) -> list[str]:
        if execution_mode == "full-access":
            return ["/"]
        sandbox_tmpdir = runtime_root / ".tmp" / "codex-sandbox"
        return [str(workspace_root), str(sandbox_tmpdir)]
