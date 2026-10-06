"""Bounded tool-free inference for app-owned background tasks."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile

from core.providers.errors import ProviderError
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import effective_provider_registry, resolve_provider_for_workspace
from core.providers.text_generation import (
    HostedTextCancellation, TextGenerationMessage, TextGenerationRequest,
    execute_hosted_text_generation,
)
from core.providers.codex_app_server_runtime_thread_params import codex_research_config
from core.providers.provider_codex_research import codex_research_environment, codex_research_runtime_version


def generate_background_text(state, *, workspace_id, app_id, request, controller, lock_fd):
    """Resolve credentials server-side and expose only output plus usage."""
    if request.get("model_source", "workspace") == "fast_model":
        cancellation = HostedTextCancellation()
        controller.register_cleanup(cancellation.cancel)
        try:
            registry = effective_provider_registry(state.provider_store, registry=getattr(state, "provider_registry", None))
            decision = select_provider_for_profile("fast_model", ProviderRoutingContext(
                workspace_id=workspace_id, provider_store=state.provider_store,
                registry=registry, secret_store=state.secret_store, app_id=app_id,
                requested_capabilities=["text_generation"],
            ))
            if decision.execution_path != "plain_hosted_text" or not decision.selected_provider_id:
                raise ProviderError("background_model_unavailable")
            result = execute_hosted_text_generation(
                state.provider_store, state.secret_store, decision=decision,
                request=TextGenerationRequest(
                    model_id=decision.selected_model_id_or_voice_id or "",
                    system_prompt=request["system_prompt"],
                    messages=[TextGenerationMessage(role="user", content=request["input_text"])],
                    max_output_tokens=request["max_output_tokens"],
                    timeout_seconds=request["timeout_seconds"], stream=False,
                    workspace_id=workspace_id,
                    provider_routing=_provider_routing(state, workspace_id, decision),
                ), app_id=app_id, cancellation=cancellation,
            )
            return {"output_text": result.output_text, "provider_id": result.provider_id,
                    "model_id": result.model_id, "usage": asdict(result.usage) if result.usage else {}}
        finally:
            controller.unregister_cleanup(cancellation.cancel)
    definition, selection = resolve_provider_for_workspace(state.provider_store, workspace_id=workspace_id)
    if definition.provider_id != "codex":
        raise ProviderError("background_native_model_unavailable")
    model = request.get("model_id") or (selection.model_id if selection else None) or definition.default_model_family
    if not model or not any(item.model_id == model for item in definition.model_options):
        raise ProviderError("background_model_selection_invalid")
    with tempfile.TemporaryDirectory(prefix="maverick-background-") as directory:
        root = Path(directory)
        executable = os.environ.get("MAVERICK_CODEX_COMMAND", "").strip() or "codex"
        if codex_research_runtime_version(executable) is None:
            raise ProviderError("background_native_runtime_unreviewed")
        private_home = root / "codex-home"
        private_home.mkdir(mode=0o700)
        source_home = Path(os.environ.get("MAVERICK_CODEX_HOME") or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
        if (source_home / "auth.json").is_file():
            shutil.copyfile(source_home / "auth.json", private_home / "auth.json")
            (private_home / "auth.json").chmod(0o600)
        environment = codex_research_environment(dict(os.environ))
        environment["CODEX_HOME"] = str(private_home)
        schema = root / "schema.json"
        output = root / "output.json"
        schema.write_text(json.dumps(request["output_schema"]), encoding="utf-8")
        command = [executable, "exec",
                   "--ephemeral", "--ignore-rules", "--sandbox", "read-only",
                   "--skip-git-repo-check", "-C", str(root), "-m", model,
                   "--json", "--output-schema", str(schema), "-o", str(output)]
        config = codex_research_config()
        config["web_search"] = "disabled"
        config["features"]["code_mode_host"] = False
        config["approval_policy"] = "never"
        config["model_reasoning_effort"] = request.get("reasoning_effort", "low")
        for key, value in config.items():
            command.extend(["-c", f"{key}={_toml(value)}"])
        command.append("-")
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True,
                                   pass_fds=(lock_fd,), env=environment)
        controller.register(process)
        try:
            stdout, _stderr = process.communicate(
                input=request["system_prompt"] + "\n\n" + request["input_text"],
                timeout=request["timeout_seconds"],
            )
            if process.returncode or not output.exists():
                raise ProviderError("background_native_generation_failed")
            if output.stat().st_size > 128_000:
                raise ProviderError("background_output_too_large")
            usage = {}
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                    usage["total_tokens"] = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            return {"output_text": output.read_text(encoding="utf-8"), "provider_id": "codex",
                    "model_id": model, "usage": usage}
        except subprocess.TimeoutExpired as error:
            raise ProviderError("background_generation_timeout") from error
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
            controller.unregister(process)


def _toml(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(k)} = {_toml(v)}" for k, v in value.items()) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


def _provider_routing(state, workspace_id, decision):
    if decision.selected_provider_id != "openrouter":
        return None
    selection = state.provider_store.get_hosted_provider_selection(workspace_id=workspace_id, profile="fast_model")
    routing = selection.openrouter_provider_routing_by_model.get(decision.selected_model_id_or_voice_id) if selection else None
    return dict(routing) if isinstance(routing, dict) else None
