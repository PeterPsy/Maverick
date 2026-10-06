"""Reviewed Antigravity primary-agent recipe for isolated public web research."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from core.providers.antigravity_cli_runtime_home import (
    _private_directory,
    _write_private_json,
    prepare_antigravity_runtime_home,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.research_runtime import RESEARCH_BOUNDARY_INSTRUCTION
from core.runtime.workspace_sandbox import build_bwrap_command


ANTIGRAVITY_RESEARCH_AGENT = "research-web-only"
ANTIGRAVITY_RESEARCH_TOOLS = frozenset({"search_web", "read_url_content"})
ANTIGRAVITY_RESEARCH_REVIEWED_VERSIONS = frozenset({"1.1.27"})


def antigravity_research_runtime_available(command: str) -> bool:
    """Recheck the executable implementing the reviewed custom-agent contract."""
    try:
        result = subprocess.run(
            [command, "--version"], capture_output=True, text=True, timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return (
        result.returncode == 0
        and result.stdout.strip() in ANTIGRAVITY_RESEARCH_REVIEWED_VERSIONS
    )


def antigravity_research_launch_spec(context, *, command, dependency_roots, auth_home):
    """Mount a private empty workdir and an auth-only home, without Core access."""
    from core.providers.antigravity_cli_sandbox import (
        resolve_antigravity_model_selection,
        resolve_antigravity_outer_sandbox,
    )

    if not antigravity_research_runtime_available(command):
        raise NativeStructuredCliError("research_runtime_unavailable")
    if (
        context.session.effective_mode != "full-access"
        or getattr(context, "secret_env", None)
        or getattr(context.binding, "credential_binding_id", None)
    ):
        raise NativeStructuredCliError("research_runtime_unavailable")
    executable = Path(shutil.which(command) or command).resolve(strict=True)
    runtime = Path(context.session.runtime_root).resolve(strict=False)
    workdir = runtime / "research-workdir"
    _private_directory(workdir, runtime)
    home = prepare_antigravity_runtime_home(runtime, source_home=auth_home)
    config = home / ".gemini" / "config"
    for name in ("agents", "skills", "rules", "plugins", "hooks"):
        target = config / name
        if target.is_symlink():
            raise NativeStructuredCliError("antigravity_runtime_home_invalid")
        if target.exists():
            shutil.rmtree(target)
        _private_directory(target, runtime)
    agent_dir = config / "agents" / ANTIGRAVITY_RESEARCH_AGENT
    _private_directory(agent_dir, runtime)
    agent = agent_dir / "agent.md"
    agent.write_text(
        "---\n"
        f"name: {ANTIGRAVITY_RESEARCH_AGENT}\n"
        "description: Public web research only.\n"
        "tools: [search_web, read_url_content]\n"
        "mainAgent: true\nsubagent: false\nmodel: inherit\n"
        "inheritCustomizations: false\ncommandExecutionPolicy: off\n"
        "skills: []\nplugins: []\nrules: []\nagents: []\nmcpServers: []\n"
        "---\n" + RESEARCH_BOUNDARY_INSTRUCTION + "\n",
        encoding="utf-8",
    )
    agent.chmod(0o600)
    _write_private_json(home / ".gemini/antigravity-cli/settings.json", {
        "enableTerminalSandbox": True,
        "toolPermission": "proceed-in-sandbox",
        "artifactReviewPolicy": "asks-for-review",
        "permissions": {"allow": []},
    })
    model, effort = resolve_antigravity_model_selection(context.binding)
    argv = [
        str(executable), "--input-format", "stream-json",
        "--output-format", "stream-json", "--agent", ANTIGRAVITY_RESEARCH_AGENT,
        "--model", model, "--mode", "plan", "--sandbox",
        "--disable-slash-commands", "--print-timeout", "24h",
        "--log-file", str(runtime / "antigravity-cli.log"),
    ]
    if effort:
        argv.extend(["--effort", effort])
    dependencies = [executable.parent, *dependency_roots]
    launch = build_bwrap_command(
        workspace_root=workdir, runtime_root=runtime, home_root=home,
        dependency_roots=dependencies, command=argv,
    )
    outer_sandbox = resolve_antigravity_outer_sandbox()
    if outer_sandbox is not None:
        launch[0] = str(outer_sandbox)
    boundary = launch.index("--")
    protected = [config / name for name in ("agents", "skills", "rules", "plugins", "hooks")]
    protected.append(config / "mcp_config.json")
    launch[boundary:boundary] = [
        argument for path in protected for argument in ("--ro-bind", str(path), str(path))
    ]
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home), "LANG": "C.UTF-8", "NO_COLOR": "1",
        "TMPDIR": str(runtime),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
    }
    return RuntimeBackendLaunchSpec(
        provider_id="antigravity-cli", command=launch, env_overrides=env,
        credential_binding_id=None, resolved_secret_refs=[],
        working_directory=str(workdir), execution_mode="sandbox",
        readable_roots=[str(workdir), str(runtime), *map(str, dependencies)],
        writable_roots=[str(runtime)],
    )


def validate_antigravity_research_init(payload, *, workdir: str) -> None:
    """Pin the selected primary agent; init.tools is the CLI's global inventory."""
    if (
        payload.get("agent") != ANTIGRAVITY_RESEARCH_AGENT
        or payload.get("permission_mode") != "proceed-in-sandbox"
        or Path(str(payload.get("cwd") or "")).resolve() != Path(workdir).resolve()
        or not ANTIGRAVITY_RESEARCH_TOOLS.issubset(payload.get("tools") or [])
    ):
        raise NativeStructuredCliError("research_runtime_unavailable")


def validate_antigravity_research_step(update) -> None:
    """Reject non-web operational events before they enter Maverick's transcript."""
    step_type = update.get("step_type") if isinstance(update, dict) else None
    if step_type not in {"user_input", "agent_response", "tool"}:
        raise NativeStructuredCliError("research_runtime_unavailable")
    if step_type == "tool":
        info = update.get("tool_info") or {}
        if not isinstance(info, dict):
            raise NativeStructuredCliError("research_runtime_unavailable")
        name = update.get("tool_name") or info.get("name")
        if name not in ANTIGRAVITY_RESEARCH_TOOLS:
            raise NativeStructuredCliError("research_runtime_unavailable")
