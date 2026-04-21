#!/usr/bin/env python3
"""Watch the main Maverick backend and launch a rescue Codex agent after sustained downtime."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.recovery.backend_watchdog import (
    BackendWatchdogState,
    backend_downtime_seconds,
    mark_rescue_agent_started,
    record_backend_probe,
    should_start_rescue_agent,
)


DEFAULT_HEALTH_URL = "http://127.0.0.1:8014/health"
DEFAULT_STATE_FILE = ".maverick/local-state/recovery/backend-watchdog.json"
DEFAULT_LOCK_FILE = ".maverick/local-state/recovery/backend-rescue-agent.lock"
DEFAULT_LOG_DIR = ".maverick/local-state/recovery/logs"
DEFAULT_CODEX_COMMAND = "codex exec --dangerously-bypass-approvals-and-sandbox --json -C /home/ubuntu/maverick-v3 -"


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


def _build_rescue_prompt(*, health_url: str, downtime_seconds: float, detail: str) -> str:
    downtime_minutes = downtime_seconds / 60
    return f"""Maverick v3 autonomous backend rescue.

Context:
- Repository: /home/ubuntu/maverick-v3
- Main backend health URL: {health_url}
- The main backend has been continuously unhealthy for about {downtime_minutes:.1f} minutes.
- Latest health failure: {detail}
- You are running from the independent rescue path with full filesystem access.

Objective:
1. Diagnose why the current Maverick v3 backend is down.
2. Read the current code and deployment files as source of truth.
3. Apply the smallest forward fix needed to restore the backend.
4. Do not use git rollback operations. Do not run `git reset`, `git checkout`, `git restore`, or any destructive history rewrite to undo work.
5. Preserve unrelated user changes. Work with the current tree.
6. Run the smallest relevant verification you can.
7. Restart the main backend with `systemctl restart maverick3-core.service` if systemd is available.
8. Verify `{health_url}` returns healthy after the fix.

Important recovery behavior:
- Do not manually recreate runtime agents.
- After the backend starts, Maverick v3 startup recovery should automatically resume interrupted running runtime sessions by queuing `resume` turns.
- If that startup recovery is broken and directly causes the outage, fix the recovery bug minimally.

Return a concise summary of diagnosis, files changed, verification, and backend health result.
"""


def _run_rescue_agent(command: str, prompt: str, *, log_dir: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"rescue-agent-{timestamp}.jsonl"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.run(
            shlex.split(command),
            input=prompt,
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=REPOSITORY_ROOT,
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
    parser.add_argument("--health-url", default=os.environ.get("MAVERICK3_CORE_HEALTH_URL", DEFAULT_HEALTH_URL))
    parser.add_argument("--state-file", type=Path, default=Path(os.environ.get("MAVERICK3_BACKEND_WATCHDOG_STATE", DEFAULT_STATE_FILE)))
    parser.add_argument("--lock-file", type=Path, default=Path(os.environ.get("MAVERICK3_BACKEND_RESCUE_LOCK", DEFAULT_LOCK_FILE)))
    parser.add_argument("--log-dir", type=Path, default=Path(os.environ.get("MAVERICK3_BACKEND_RESCUE_LOG_DIR", DEFAULT_LOG_DIR)))
    parser.add_argument("--threshold-seconds", type=int, default=int(os.environ.get("MAVERICK3_BACKEND_RESCUE_THRESHOLD_SECONDS", "300")))
    parser.add_argument("--cooldown-seconds", type=int, default=int(os.environ.get("MAVERICK3_BACKEND_RESCUE_COOLDOWN_SECONDS", "1800")))
    parser.add_argument("--probe-timeout-seconds", type=float, default=float(os.environ.get("MAVERICK3_BACKEND_HEALTH_TIMEOUT_SECONDS", "5")))
    parser.add_argument("--codex-command", default=os.environ.get("MAVERICK3_RESCUE_CODEX_COMMAND", DEFAULT_CODEX_COMMAND))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

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
        state = mark_rescue_agent_started(state, now=now)
        _write_state(args.state_file, state)
        prompt = _build_rescue_prompt(health_url=args.health_url, downtime_seconds=downtime, detail=detail)
        if args.dry_run:
            print(prompt)
            return 0
        return _run_rescue_agent(args.codex_command, prompt, log_dir=args.log_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
