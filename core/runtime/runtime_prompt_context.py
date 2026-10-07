"""Workspace context shared by native CLI and hosted provider projections."""

from __future__ import annotations

import json
from pathlib import Path

from core.device_use.contract import device_use_instructions
from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.workspace_instructions import (
    resolve_workspace_instruction_chain,
    workspace_relative_workdir,
)
from core.runtime.research_runtime import runtime_session_is_research


def runtime_environment_context(session, *, native: bool = False) -> dict[str, str]:
    """Describe the active workspace in the namespace available to its tools."""
    workspace = Path(session.workspace_root)
    relative_workdir = workspace_relative_workdir(
        workspace_root=workspace, workdir=session.workdir,
    )
    host_paths = native or session.effective_mode == "full-access"
    root = str(workspace) if host_paths else f"workspace://{session.workspace_id}"
    workdir = root if relative_workdir == "." else f"{root}/{relative_workdir}"
    return {
        "workspace_id": session.workspace_id,
        "workspace_root": root,
        "workdir": workdir,
        "execution_mode": session.effective_mode,
        "filesystem_scope": (
            "host" if session.effective_mode == "full-access" else "workspace"
        ),
    }


def native_runtime_input(*, session, input_text: str, skills=()) -> str:
    """Supply context for CLIs without Codex's native instruction discovery."""
    if runtime_session_is_research(session):
        return input_text
    device_use_binding = getattr(session, "device_use_binding", None)
    sections = [
        "[Maverick runtime context]\n"
        "An active workspace is available. Use filesystem tools to inspect it "
        "before reporting whether a repository is available. Full-access mode "
        "permits host paths outside the workspace; sandbox mode is confined to "
        "the workspace. Read applicable AGENTS.md files before changing code. "
        "The maverick CLI exposes Core and app tools: start with "
        "`maverick core cli list --json` and `maverick apps list --json`.\n"
        + json.dumps(runtime_environment_context(session, native=True), ensure_ascii=False)
    ]
    filesystem = ConfinedWorkspaceFilesystem(
        workspace_id=session.workspace_id,
        workspace_root=Path(session.workspace_root),
    )
    try:
        instructions = resolve_workspace_instruction_chain(
            filesystem,
            workspace_root=Path(session.workspace_root),
            workdir=session.workdir,
        )
        for instruction in instructions:
            sections.append(
                f"[Workspace instructions: {instruction.relative_path}]\n"
                + instruction.content
            )
    finally:
        filesystem.close()
    if getattr(session, "system_prompt", None):
        sections.append("[Agent instructions]\n" + session.system_prompt)
    if skills:
        sections.append(
            "[Available skills]\n"
            "Read a skill's SKILL.md before using it.\n"
            + json.dumps(
                [
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "path": str(Path(skill.source_root) / "SKILL.md"),
                    }
                    for skill in skills
                ],
                ensure_ascii=False,
            )
        )
    if device_use_binding is not None:
        sections.append(
            "[Additional Mac capability]\n" + device_use_instructions(
                mode=device_use_binding.mode,
                approved_apps=device_use_binding.approved_apps,
                initial_app=device_use_binding.initial_app,
            )
        )
    sections.append("[Maverick user input]\n" + input_text)
    return "\n\n".join(sections)
