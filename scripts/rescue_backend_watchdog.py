#!/usr/bin/env python3
"""Watch the main Maverick backend and launch the configured rescue provider after sustained downtime."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.providers.errors import ProviderError, ProviderSelectionError
from core.recovery.backend_rescue import build_backend_rescue_command
from core.recovery.backend_watchdog import (
    BackendWatchdogState,
    backend_downtime_seconds,
    mark_rescue_agent_blocked,
    mark_rescue_agent_started,
    record_backend_probe,
    should_start_rescue_agent,
)


DEFAULT_HEALTH_URL = "http://127.0.0.1:8014/health"
DEFAULT_STATE_FILE = "tmp/recovery/backend-watchdog.json"
DEFAULT_LOCK_FILE = "tmp/recovery/backend-rescue-agent.lock"
DEFAULT_LOG_DIR = "tmp/recovery/logs"
DEFAULT_PROVIDER_WORKSPACE_ID = "default"


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _read_state(path: Path) -> BackendWatchdogState:
    if not path.exists():
        return BackendWatchdogState()
    return BackendWatchdogState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_state(path: Path, state: BackendWatchdogState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _probe_backend(url: str, *, timeout_seconds: float) -> tuple[bool, str]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            if response.status != 200:
                return False, f"health returned HTTP {response.status}: {body[:300]}"
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return False, f"health returned non-JSON body: {body[:300]}"
            if payload.get("status") == "ok":
                return True, "backend health returned ok"
            return False, f"health returned non-ok payload: {payload}"
    except HTTPError as error:
        detail = error.read(512).decode("utf-8", errors="replace")
        return False, f"health returned HTTP {error.code}: {detail}"
    except URLError as error:
        return False, f"health request failed: {error.reason}"
    except OSError as error:
        return False, f"health request failed: {error}"


def _build_rescue_prompt(*, repository_root: Path, health_url: str, downtime_seconds: float, detail: str) -> str:
    downtime_minutes = downtime_seconds / 60
    return f"""Maverick autonomous backend rescue.

Context:
- Repository: {repository_root}
- Main backend health URL: {health_url}
- The main backend has been continuously unhealthy for about {downtime_minutes:.1f} minutes.
- Latest health failure: {detail}
- You are running from the independent rescue path with full filesystem access.

Objective:
1. Diagnose why the current Maverick backend is down.
2. Read the current code and deployment files as source of truth.
3. Apply the smallest forward fix needed to restore the backend.
4. Do not use git rollback operations. Do not run `git reset`, `git checkout`, `git restore`, or any destructive history rewrite to undo work.
5. Preserve unrelated user changes. Work with the current tree.
6. Run the smallest relevant verification you can.
7. Restart the main backend with `systemctl restart maverick-core.service` if systemd is available.
8. Verify `{health_url}` returns healthy after the fix.

Important recovery behavior:
- Do not manually recreate runtime agents.
- After the backend starts, Maverick startup recovery should automatically resume interrupted running runtime sessions by queuing `resume` turns.
- If that startup recovery is broken and directly causes the outage, fix the recovery bug minimally.

Return a concise summary of diagnosis, files changed, verification, and backend health result.
"""


def _run_rescue_agent(command: list[str], prompt: str, *, log_dir: Path, repository_root: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"rescue-agent-{timestamp}.jsonl"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=repository_root,
            check=False,
        )
    print(f"rescue agent exited with {process.returncode}; log={log_path}")
    return process.returncode


def _try_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f"pid={os.getpid()} started_at={_utc_now().isoformat()}\n")
    lock_file.flush()
    return lock_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--health-url", default=os.environ.get("MAVERICK_CORE_HEALTH_URL", DEFAULT_HEALTH_URL))
    parser.add_argument("--state-file", type=Path, default=Path(os.environ.get("MAVERICK_BACKEND_WATCHDOG_STATE", DEFAULT_STATE_FILE)))
    parser.add_argument("--lock-file", type=Path, default=Path(os.environ.get("MAVERICK_BACKEND_RESCUE_LOCK", DEFAULT_LOCK_FILE)))
    parser.add_argument("--log-dir", type=Path, default=Path(os.environ.get("MAVERICK_BACKEND_RESCUE_LOG_DIR", DEFAULT_LOG_DIR)))
    parser.add_argument("--threshold-seconds", type=int, default=int(os.environ.get("MAVERICK_BACKEND_RESCUE_THRESHOLD_SECONDS", "300")))
    parser.add_argument("--cooldown-seconds", type=int, default=int(os.environ.get("MAVERICK_BACKEND_RESCUE_COOLDOWN_SECONDS", "1800")))
    parser.add_argument("--probe-timeout-seconds", type=float, default=float(os.environ.get("MAVERICK_BACKEND_HEALTH_TIMEOUT_SECONDS", "5")))
    parser.add_argument("--provider-workspace-id", default=os.environ.get("MAVERICK_RECOVERY_PROVIDER_WORKSPACE_ID", DEFAULT_PROVIDER_WORKSPACE_ID))
    parser.add_argument("--codex-command", default=os.environ.get("MAVERICK_CODEX_COMMAND", "codex"))
    parser.add_argument(
        "--provider-command-override",
        "--rescue-command",
        dest="provider_command_override",
        default=os.environ.get("MAVERICK_BACKEND_RESCUE_COMMAND", ""),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    repository_root = args.repository_root.resolve()

    now = _utc_now()
    state = _read_state(args.state_file)
    healthy, detail = _probe_backend(args.health_url, timeout_seconds=args.probe_timeout_seconds)
    state = record_backend_probe(state, healthy=healthy, detail=detail, now=now)
    downtime = backend_downtime_seconds(state, now=now)

    if not should_start_rescue_agent(
        state,
        threshold_seconds=args.threshold_seconds,
        cooldown_seconds=args.cooldown_seconds,
        now=now,
    ):
        _write_state(args.state_file, state)
        print(json.dumps({"healthy": healthy, "detail": detail, "downtime_seconds": downtime, "rescue_started": False}))
        return 0

    lock_file = _try_lock(args.lock_file)
    if lock_file is None:
        _write_state(args.state_file, state)
        print(json.dumps({"healthy": healthy, "detail": detail, "downtime_seconds": downtime, "rescue_started": False, "reason": "locked"}))
        return 0

    with lock_file:
        prompt = _build_rescue_prompt(
            repository_root=repository_root,
            health_url=args.health_url,
            downtime_seconds=downtime,
            detail=detail,
        )
        try:
            rescue_command = build_backend_rescue_command(
                repository_root=repository_root,
                workspace_id=args.provider_workspace_id,
                codex_command=args.codex_command,
                provider_command_override=args.provider_command_override,
            )
        except ProviderSelectionError as error:
            blocked_reason = "no_provider_configured" if str(error) == "no_provider_configured" else "provider_unavailable"
            state = mark_rescue_agent_blocked(state, reason=blocked_reason, detail=str(error), now=now)
            _write_state(args.state_file, state)
            print(
                json.dumps(
                    {
                        "healthy": healthy,
                        "detail": detail,
                        "downtime_seconds": downtime,
                        "rescue_started": False,
                        "blocked_reason": blocked_reason,
                        "blocked_detail": str(error),
                    }
                )
            )
            return 0
        except ProviderError as error:
            state = mark_rescue_agent_blocked(state, reason="provider_unavailable", detail=str(error), now=now)
            _write_state(args.state_file, state)
            print(
                json.dumps(
                    {
                        "healthy": healthy,
                        "detail": detail,
                        "downtime_seconds": downtime,
                        "rescue_started": False,
                        "blocked_reason": "provider_unavailable",
                        "blocked_detail": str(error),
                    }
                )
            )
            return 0
        if args.dry_run:
            print(prompt)
            print(json.dumps({"provider_id": rescue_command.provider_id, "command": rescue_command.command}))
            return 0
        state = mark_rescue_agent_started(state, now=now)
        _write_state(args.state_file, state)
        return _run_rescue_agent(rescue_command.command, prompt, log_dir=args.log_dir, repository_root=repository_root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
