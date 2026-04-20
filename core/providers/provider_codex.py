"""Codex runtime backend adapter."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING

from core.providers.errors import ProviderLaunchError
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.runtime.runtime_session import RuntimeSessionRecord

if TYPE_CHECKING:
    from core.skills.models import SkillDefinition, SkillMaterialization

CODEX_RUNTIME_HOME_FILES = ("auth.json", "version.json", ".personality_migration", "installation_id")
CODEX_DISABLED_RUNTIME_FEATURES = ("apps", "plugins")
CODEX_SYSTEM_SKILLS_ROOT = ".system"
CODEX_MANAGED_RUNTIME_FEATURES = {
    "apps": False,
    "plugins": False,
    "skill_mcp_dependency_install": False,
}


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
        codex_command: str | None = None,
        server_args: list[str] | None = None,
    ) -> None:
        self.codex_command = str(codex_command or os.environ.get("MAVERICK3_CODEX_COMMAND") or "").strip() or "codex"
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

    def build_launch_spec(
        self,
        session: RuntimeSessionRecord,
        *,
        secret_env: dict[str, str] | None = None,
        credential_binding_id: str | None = None,
        resolved_secret_refs: list[str] | None = None,
    ) -> RuntimeBackendLaunchSpec:
        """Build one runtime launch spec for the local Codex backend."""
        self.validate_backend()
        workdir = Path(session.workdir)
        workspace_root = Path(session.workspace_root)
        runtime_root = Path(session.runtime_root)
        runtime_home = self._prepare_runtime_home(session)
        env = self._build_subprocess_env(
            workdir=workdir,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            runtime_home=runtime_home,
            execution_mode=session.effective_mode,
            secret_env=secret_env,
        )
        return RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=self._build_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                execution_mode=session.effective_mode,
            ),
            env_overrides=env,
            credential_binding_id=credential_binding_id,
            resolved_secret_refs=list(resolved_secret_refs or []),
            working_directory=str(workdir),
            execution_mode=session.effective_mode,
            readable_roots=self._readable_roots(
                workspace_root=workspace_root,
                execution_mode=session.effective_mode,
            ),
            writable_roots=self._writable_roots(
                workspace_root=workspace_root,
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
            target_root = skills_root.joinpath(*skill.skill_id.split("."))
            if target_root.exists() or target_root.is_symlink():
                if target_root.is_symlink() or target_root.is_file():
                    target_root.unlink()
                else:
                    shutil.rmtree(target_root)
            target_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_root, target_root, dirs_exist_ok=True)
            materializations.append(
                SkillMaterialization(
                    provider_id="codex",
                    skill_id=skill.skill_id,
                    source_root=str(source_root),
                    target_root=str(target_root),
                    strategy="copy",
                )
            )
        return materializations

    def _build_command(self, *, workspace_root: Path, runtime_root: Path, execution_mode: str) -> list[str]:
        host_command = self._runtime_command(self.codex_command)
        command = [host_command]
        for feature in CODEX_DISABLED_RUNTIME_FEATURES:
            command.extend(["--disable", feature])
        command.extend(self.server_args)
        if execution_mode == "full-access":
            return command
        dependency_args = self._dependency_root_args(host_command)
        host_command_path = Path(host_command)
        if self._is_standalone_codex_binary(host_command_path):
            sandbox_command = runtime_root / "bin" / "codex"
            dependency_args = ["--dependency-file", f"{host_command_path}={sandbox_command}"]
            command[0] = str(sandbox_command)
        return [
            sys.executable,
            "-m",
            "core.runtime.workspace_sandbox",
            "--workspace-root",
            str(workspace_root),
            "--runtime-root",
            str(runtime_root),
            *dependency_args,
            "--",
            *command,
        ]

    def _build_subprocess_env(
        self,
        *,
        workdir: Path,
        workspace_root: Path,
        runtime_root: Path,
        runtime_home: Path,
        execution_mode: str,
        secret_env: dict[str, str] | None = None,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(base_env or os.environ)
        env.update(secret_env or {})
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
            runtime_root.mkdir(parents=True, exist_ok=True)
            env["TMPDIR"] = str(runtime_root)
            env["TMP"] = str(runtime_root)
            env["TEMP"] = str(runtime_root)
            env["HOME"] = str(runtime_home)
            env["PYTHONPATH"] = self._runtime_pythonpath(env.get("PYTHONPATH"))
        return env

    def _runtime_home(self, session: RuntimeSessionRecord) -> Path:
        return Path(session.runtime_root) / "codex-home"

    def _prepare_runtime_home(self, session: RuntimeSessionRecord) -> Path:
        runtime_home = self._runtime_home(session)
        runtime_home.mkdir(parents=True, exist_ok=True)
        source_home = self._source_codex_home()
        if self._same_path(runtime_home, source_home):
            return runtime_home
        self._remove_disabled_runtime_material(runtime_home)
        for filename in CODEX_RUNTIME_HOME_FILES:
            self._copy_file_if_present(source_home / filename, runtime_home / filename)
        self._write_runtime_config(
            source_home / "config.toml",
            runtime_home / "config.toml",
            workspace_root=Path(session.workspace_root),
            execution_mode=session.effective_mode,
        )
        self._link_or_copy_if_present(source_home / "rules", runtime_home / "rules")
        self._remove_disabled_runtime_material(runtime_home)
        remove_codex_system_skills(runtime_home)
        return runtime_home

    def _source_codex_home(self) -> Path:
        configured = str(os.environ.get("MAVERICK3_CODEX_HOME") or os.environ.get("CODEX_HOME") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".codex"

    def _same_path(self, left: Path, right: Path) -> bool:
        try:
            return left.resolve(strict=False) == right.resolve(strict=False)
        except OSError:
            return False

    def _copy_file_if_present(self, source: Path, destination: Path) -> None:
        if not source.is_file():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _write_runtime_config(self, source: Path, destination: Path, *, workspace_root: Path, execution_mode: str) -> None:
        raw_lines = source.read_text(encoding="utf-8").splitlines() if source.is_file() else []
        sanitized_lines: list[str] = []
        skipping_disabled_section = False
        for line in raw_lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                skipping_disabled_section = self._is_disabled_runtime_config_section(
                    stripped,
                    workspace_root=workspace_root,
                    execution_mode=execution_mode,
                )
                if skipping_disabled_section:
                    continue
            if skipping_disabled_section:
                continue
            sanitized_lines.append(line)
        if sanitized_lines and sanitized_lines[-1].strip():
            sanitized_lines.append("")
        sanitized_lines.extend(self._managed_runtime_feature_lines())
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(sanitized_lines).strip() + "\n", encoding="utf-8")

    def _is_disabled_runtime_config_section(self, section: str, *, workspace_root: Path, execution_mode: str) -> bool:
        if section in {"[mcp_servers]", "[plugins]", "[features]"}:
            return True
        if section.startswith(("[mcp_servers.", "[plugins.", "[features.")):
            return True
        return self._is_sandbox_project_section_outside_workspace(
            section,
            workspace_root=workspace_root,
            execution_mode=execution_mode,
        )

    def _is_sandbox_project_section_outside_workspace(self, section: str, *, workspace_root: Path, execution_mode: str) -> bool:
        if execution_mode != "sandbox":
            return False
        prefix = "[projects."
        if not section.startswith(prefix) or not section.endswith("]"):
            return False
        raw_project = section[len(prefix) : -1].strip()
        if len(raw_project) >= 2 and raw_project[0] == raw_project[-1] and raw_project[0] in {'"', "'"}:
            raw_project = raw_project[1:-1]
        if not raw_project:
            return True
        workspace = workspace_root.expanduser().resolve(strict=False)
        project = Path(raw_project).expanduser().resolve(strict=False)
        return project != workspace and not project.is_relative_to(workspace)

    def _managed_runtime_feature_lines(self) -> list[str]:
        lines = ["[features]"]
        for name, enabled in CODEX_MANAGED_RUNTIME_FEATURES.items():
            lines.append(f"{name} = {str(enabled).lower()}")
        return lines

    def _remove_disabled_runtime_material(self, runtime_home: Path) -> None:
        for path in (
            runtime_home / "plugins",
            runtime_home / "skills" / CODEX_SYSTEM_SKILLS_ROOT,
            runtime_home / "cache" / "codex_apps_tools",
            runtime_home / ".tmp" / "plugins",
            runtime_home / ".tmp" / "plugins.sha",
            runtime_home / ".tmp" / "app-server-remote-plugin-sync-v1",
        ):
            self._reset_path(path)

    def _link_or_copy_if_present(self, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        self._reset_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)

    def _reset_path(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    def _readable_roots(self, *, workspace_root: Path, execution_mode: str) -> list[str]:
        if execution_mode == "full-access":
            return ["/"]
        return [str(workspace_root)]

    def _writable_roots(self, *, workspace_root: Path, execution_mode: str) -> list[str]:
        if execution_mode == "full-access":
            return ["/"]
        return [str(workspace_root)]

    def _dependency_root_args(self, command: str) -> list[str]:
        roots = self._command_dependency_roots(command)
        args: list[str] = []
        for root in roots:
            args.extend(["--dependency-root", str(root)])
        return args

    def _runtime_command(self, command: str) -> str:
        command_path = self._command_path(command)
        if command_path is None:
            return command
        resolved = command_path.resolve(strict=False)
        standalone = self._standalone_codex_binary(resolved)
        return str(standalone or command_path)

    def _command_dependency_roots(self, command: str) -> list[Path]:
        command_path = self._command_path(command)
        if command_path is None:
            return []
        resolved = command_path.resolve(strict=False)
        if self._is_standalone_codex_binary(resolved):
            return [resolved.parent]
        standalone = self._standalone_codex_binary(resolved)
        if standalone is not None:
            return [standalone.parent]
        nvm_node_versions = Path.home() / ".nvm" / "versions" / "node"
        try:
            if resolved.is_relative_to(nvm_node_versions):
                relative = resolved.relative_to(nvm_node_versions)
                if relative.parts:
                    return [nvm_node_versions / relative.parts[0]]
        except OSError:
            pass
        if any(resolved.is_relative_to(Path(root)) for root in ("/usr", "/bin", "/lib", "/lib64")):
            return []
        return [resolved.parent]

    def _command_path(self, command: str) -> Path | None:
        path_entries = [entry for entry in str(os.environ.get("PATH") or "").split(os.pathsep) if entry]
        resolved_value = command if os.sep in command else shutil.which(command, path=os.pathsep.join(path_entries))
        if not resolved_value:
            return None
        return Path(resolved_value).expanduser()

    def _standalone_codex_binary(self, resolved: Path) -> Path | None:
        if self._is_standalone_codex_binary(resolved):
            return resolved
        package_root = resolved.parent.parent if resolved.name == "codex.js" and resolved.parent.name == "bin" else None
        if package_root is None or package_root.name != "codex":
            return None
        vendor_root = package_root / "node_modules" / "@openai"
        if not vendor_root.exists():
            return None
        candidates = sorted(vendor_root.glob("codex-linux-*/vendor/*/codex/codex"))
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve(strict=False)
        return None

    def _is_standalone_codex_binary(self, resolved: Path) -> bool:
        return resolved.name == "codex" and resolved.parent.name == "codex" and "vendor" in resolved.parts

    def _runtime_pythonpath(self, existing: str | None) -> str:
        repo_root = Path(__file__).resolve().parents[2]
        entries = [str(repo_root)]
        entries.extend(entry for entry in str(existing or "").split(os.pathsep) if entry)
        seen: set[str] = set()
        unique: list[str] = []
        for entry in entries:
            if entry in seen:
                continue
            seen.add(entry)
            unique.append(entry)
        return os.pathsep.join(unique)


def remove_codex_system_skills(runtime_home: Path) -> None:
    """Remove Codex-generated system skills from a Maverick-managed runtime home."""
    system_root = Path(runtime_home) / "skills" / CODEX_SYSTEM_SKILLS_ROOT
    if system_root.is_symlink() or system_root.is_file():
        system_root.unlink(missing_ok=True)
        return
    if system_root.is_dir():
        shutil.rmtree(system_root, ignore_errors=True)
