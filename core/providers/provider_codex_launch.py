"""Codex runtime backend adapter."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Callable

from core.providers.errors import ProviderLaunchError
from core.providers.models import (
    ProviderCapabilitySet,
    ProviderDefinition,
    ProviderModelOption,
    ProviderReasoningOption,
    RuntimeBackendLaunchSpec,
)
from core.providers.provider_codex_reasoning import (
    CODEX_DEFAULT_REASONING_EFFORT,
    codex_default_reasoning_effort,
    normalize_codex_model_options,
)
from core.runtime.execution_events import RuntimeExecutionEventSink
from core.runtime.runtime_session import RuntimeSessionRecord

if TYPE_CHECKING:
    from core.runtime.execution import RuntimeExecutionResult
    from core.skills.models import SkillDefinition, SkillMaterialization

CODEX_RUNTIME_HOME_FILES = ("auth.json", "version.json", ".personality_migration", "installation_id")
CODEX_DISABLED_RUNTIME_FEATURES = ("apps", "plugins")
CODEX_SYSTEM_SKILLS_ROOT = ".system"
CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
CODEX_MANAGED_TOP_LEVEL_CONFIG_KEYS = {"model", "model_reasoning_effort"}
CODEX_MANAGED_RUNTIME_FEATURES = {
    "apps": False,
    "plugins": False,
    "skill_mcp_dependency_install": False,
}
CODEX_SKILL_MANIFEST_FILE = ".maverick_skill_manifest.json"


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _codex_executable() -> str:
    configured = os.environ.get("MAVERICK_CODEX_COMMAND", "").strip()
    if configured:
        return configured
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    return "codex"


def _codex_app_server_command(*, execution_mode: str, codex_command: str | None = None) -> list[str]:
    """Return the canonical Codex app-server command for interactive sessions."""
    command = [str(codex_command or "").strip() or _codex_executable()]
    command.extend(["app-server", "--listen", "stdio://"])
    return command


def build_codex_definition(
    now: datetime | None = None,
    *,
    model_options: list[ProviderModelOption] | None = None,
    default_model_id: str | None = None,
) -> ProviderDefinition:
    """Build the canonical provider definition for the local Codex backend."""
    timestamp = now or utcnow()
    options = normalize_codex_model_options(list(model_options or _fallback_model_options()))
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
            supports_same_turn_input=True,
        ),
        default_model_family=default_model_id or _default_model_id(options),
        requires_credentials=False,
        supported_execution_modes=["sandbox", "full-access"],
        created_at=timestamp,
        updated_at=timestamp,
        model_options=options,
    )


def _fallback_model_options() -> list[ProviderModelOption]:
    return [
        ProviderModelOption(
            model_id=CODEX_DEFAULT_MODEL,
            label=CODEX_DEFAULT_MODEL,
            description="Default Codex model configured by Maverick when the Codex model catalog cannot be read.",
            default_reasoning_effort=CODEX_DEFAULT_REASONING_EFFORT,
            supported_reasoning_efforts=_fallback_reasoning_options(),
        )
    ]


def _fallback_reasoning_options() -> list[ProviderReasoningOption]:
    return [
        ProviderReasoningOption(effort="low", label="Low", description="Fast responses with lighter reasoning"),
        ProviderReasoningOption(effort="medium", label="Mid", description="Balanced reasoning depth"),
        ProviderReasoningOption(effort="high", label="High", description="Greater reasoning depth"),
        ProviderReasoningOption(effort="xhigh", label="Extra high", description="Very deep reasoning"),
        ProviderReasoningOption(effort="max", label="Max", description="Maximum single-agent reasoning depth"),
    ]


def _default_model_id(options: list[ProviderModelOption]) -> str:
    option_ids = [option.model_id for option in options]
    if CODEX_DEFAULT_MODEL in option_ids:
        return CODEX_DEFAULT_MODEL
    return option_ids[0] if option_ids else CODEX_DEFAULT_MODEL


def _default_reasoning_effort(option: ProviderModelOption | None) -> str | None:
    return codex_default_reasoning_effort(option)




def _skill_manifest(skills: list["SkillDefinition"]) -> dict[str, object]:
    """Build a cheap invalidation manifest for the selected workspace skill set."""
    items: list[dict[str, str]] = []
    for skill in sorted(skills, key=lambda item: item.skill_id):
        source_root = Path(skill.source_root).resolve()
        items.append(
            {
                "skill_id": skill.skill_id,
                "source_root": str(source_root),
                "source_metadata_hash": _directory_metadata_hash(source_root),
            }
        )
    digest = hashlib.sha256(
        json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"version": 2, "hash": digest, "skills": items}


def _directory_metadata_hash(root: Path) -> str:
    """Hash recursive path, mtime, and size metadata without reading file contents."""
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"missing")
        digest.update(str(root).encode("utf-8"))
        return digest.hexdigest()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        try:
            stat = path.stat()
        except OSError:
            digest.update(b"unreadable")
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"dir" if path.is_dir() else b"file")
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _read_skill_manifest(manifest_path: Path) -> dict[str, object] | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _skill_ids_from_manifest(manifest: dict[str, object] | None) -> set[str]:
    skill_items = manifest.get("skills") if isinstance(manifest, dict) else None
    if not isinstance(skill_items, list):
        return set()
    skill_ids: set[str] = set()
    for item in skill_items:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id") or "").strip()
        if skill_id:
            skill_ids.add(skill_id)
    return skill_ids


def _skill_target_root(skills_root: Path, skill_id: str) -> Path | None:
    parts = [part for part in str(skill_id or "").strip().split(".") if part]
    if not parts:
        return None
    if any(part in {".", "..", CODEX_SYSTEM_SKILLS_ROOT} or "/" in part or "\\" in part for part in parts):
        return None
    return skills_root.joinpath(*parts)


def _skill_target_parts(skills_root: Path, skill_id: str) -> tuple[str, ...] | None:
    target_root = _skill_target_root(skills_root, skill_id)
    if target_root is None:
        return None
    try:
        return target_root.relative_to(skills_root).parts
    except ValueError:
        return None


def _skill_manifest_current(manifest_path: Path, manifest: dict[str, object], skills_root: Path) -> bool:
    current = _read_skill_manifest(manifest_path)
    if current is None:
        return False
    if current != manifest:
        return False
    for skill_id in _skill_ids_from_manifest(manifest):
        target_root = _skill_target_root(skills_root, skill_id)
        if target_root is None or not target_root.is_dir():
            return False
    return True


def _write_skill_manifest(manifest_path: Path, manifest: dict[str, object]) -> None:
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _remove_unmanifested_skill_directories(skills_root: Path, manifest: dict[str, object]) -> None:
    current_targets = {
        parts
        for skill_id in _skill_ids_from_manifest(manifest)
        if (parts := _skill_target_parts(skills_root, skill_id)) is not None
    }

    def current_target_has_prefix(prefix: tuple[str, ...]) -> bool:
        return any(target[: len(prefix)] == prefix for target in current_targets)

    def visit(directory: Path, prefix: tuple[str, ...]) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            if child.name in {CODEX_SYSTEM_SKILLS_ROOT, CODEX_SKILL_MANIFEST_FILE}:
                continue
            child_prefix = (*prefix, child.name)
            if child_prefix in current_targets:
                continue
            if current_target_has_prefix(child_prefix):
                if child.is_dir() and not child.is_symlink():
                    visit(child, child_prefix)
                    _remove_empty_skill_parents(skills_root, child)
                continue
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)

    visit(skills_root, ())


def _remove_empty_skill_parents(skills_root: Path, start: Path) -> None:
    current = start
    while current != skills_root and skills_root in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


class CodexLaunchMixin:
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
        model_id: str | None = None,
        model_reasoning_effort: str | None = None,
    ) -> RuntimeBackendLaunchSpec:
        """Build one runtime launch spec for the local Codex backend."""
        self.validate_backend()
        selected_model, selected_reasoning = self.validate_model_settings(model_id, model_reasoning_effort)
        workdir = Path(session.workdir)
        workspace_root = Path(session.workspace_root)
        runtime_root = Path(session.runtime_root)
        host_command = self._runtime_command(self.codex_command)
        runtime_bin = self._prepare_runtime_bin(session, host_command=host_command)
        runtime_home = self._runtime_home(session)
        env = self._build_subprocess_env(
            workdir=workdir,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            runtime_home=runtime_home,
            runtime_bin=runtime_bin,
            session=session,
            execution_mode=session.effective_mode,
            secret_env=secret_env,
        )
        runtime_home = self._prepare_runtime_home(
            session,
            runtime_bin=runtime_bin,
            shell_path=env.get("PATH"),
            model_id=selected_model,
            model_reasoning_effort=selected_reasoning,
        )
        return RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=self._build_command(
                workspace_root=workspace_root,
                runtime_root=runtime_root,
                runtime_home=runtime_home,
                runtime_bin=runtime_bin,
                execution_mode=session.effective_mode,
                host_command=host_command,
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
        manifest_path = skills_root / CODEX_SKILL_MANIFEST_FILE
        manifest = _skill_manifest(skills)
        if _skill_manifest_current(manifest_path, manifest, skills_root):
            _remove_unmanifested_skill_directories(skills_root, manifest)
            return [
                SkillMaterialization(
                    provider_id="codex",
                    skill_id=skill.skill_id,
                    source_root=str(Path(skill.source_root).resolve()),
                    target_root=str(
                        _skill_target_root(skills_root, skill.skill_id)
                        or skills_root.joinpath(*skill.skill_id.split("."))
                    ),
                    strategy="copy",
                )
                for skill in skills
            ]
        _remove_unmanifested_skill_directories(skills_root, manifest)
        materializations: list[SkillMaterialization] = []
        for skill in skills:
            source_root = Path(skill.source_root).resolve()
            target_root = _skill_target_root(skills_root, skill.skill_id)
            if target_root is None:
                continue
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
        _write_skill_manifest(manifest_path, manifest)
        return materializations



    def execute_turn(
        self,
        *,
        session: RuntimeSessionRecord,
        launch_spec: RuntimeBackendLaunchSpec,
        input_text: str,
        invoked_skills: list["SkillDefinition"] | None = None,
        event_sink: RuntimeExecutionEventSink | None = None,
        timeout_seconds: int | None = None,
        on_provider_thread_id: Callable[[str], None] | None = None,
        on_provider_startup_event: Callable[[str, dict[str, object]], None] | None = None,
        on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
        on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
        command_runner=subprocess.Popen,
    ) -> "RuntimeExecutionResult":
        """Execute one turn through the Codex app-server runtime."""
        from core.providers.codex_app_server import execute_codex_app_server_turn
        from core.runtime.execution import RuntimeExecutionResult

        result = execute_codex_app_server_turn(
            session=session,
            launch_spec=launch_spec,
            input_text=input_text,
            invoked_skills=invoked_skills,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
            on_provider_thread_id=on_provider_thread_id,
            on_provider_startup_event=on_provider_startup_event,
            on_provider_turn_start_sent=on_provider_turn_start_sent,
            on_provider_accepted=on_provider_accepted,
            command_runner=command_runner,
        )
        return RuntimeExecutionResult(output_text=result.output_text, exit_code=result.exit_code)



    def close_runtime(self, session_id: str) -> int:
        """Close any persistent Codex app-server runtime for one session."""
        from core.providers.codex_app_server import close_codex_app_server_runtime

        return close_codex_app_server_runtime(session_id)

    def interrupt_turn(self, session_id: str) -> bool:
        """Interrupt the active Codex app-server turn for one session."""
        from core.providers.codex_app_server import interrupt_codex_app_server_turn

        return interrupt_codex_app_server_turn(session_id)
