"""Private filesystem and credential scope for the tool-only UI process."""

import os
from pathlib import Path
import shutil

from core.providers.provider_codex_research import codex_research_environment


def computer_actor_launch(session, adapter):
    root = Path(session.runtime_root) / "computer-actor"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    home, workdir, runtime_bin = root / "codex-home", root / "workdir", root / "bin"
    for path in (home, workdir, runtime_bin):
        path.mkdir(exist_ok=True, mode=0o700)
    source = adapter._source_codex_home() / "auth.json"
    if not source.is_file():
        raise RuntimeError("computer_actor_codex_auth_unavailable")
    shutil.copyfile(source, home / "auth.json")
    (home / "auth.json").chmod(0o600)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "runtime" / "workspace_sandbox.py",
                    runtime_bin / "workspace_sandbox.py")
    command = adapter._build_command(workspace_root=workdir, runtime_root=root,
        runtime_home=home, runtime_bin=runtime_bin, execution_mode="sandbox",
        host_command=adapter._runtime_command(adapter.codex_command), require_code_mode_host=True)
    env = {**codex_research_environment(dict(os.environ)), "CODEX_HOME": str(home),
           "MAVERICK_RUNTIME_SESSION_ID": session.session_id,
           "MAVERICK_RUNTIME_ENGINE_ID": "codex-computer-actor"}
    return command, env, home, workdir
