"""Content-preserving Codex CLI transport used by OpenDesign's native adapter."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys


EXPECTED_SOCKET = Path("/model-access/broker.sock")
EXPECTED_PROFILE = Path(
    "/data/opendesign-native/sandbox/agent-home/.maverick/model-access-agents.json"
)
CLI_PROFILE_ID = "installed-codex-cli"
MAX_STDIN_BYTES = 32 * 1024 * 1024
MAX_PROFILE_BYTES = 2 * 1024 * 1024


def main() -> int:
    socket_path, token = _configuration()
    arguments = tuple(sys.argv[1:])
    _validate_selected_model(arguments)
    stdin = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(stdin) > MAX_STDIN_BYTES:
        raise RuntimeError("Codex input exceeds the model bridge limit")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(str(socket_path))
    argv = _encoded(json.dumps(arguments, separators=(",", ":")))
    cwd = _encoded(os.getcwd())
    request = (
        "POST /maverick/v1/cli/codex/exec HTTP/1.1\r\n"
        f"Authorization: Bearer {token}\r\n"
        f"Content-Length: {len(stdin)}\r\n"
        f"X-Maverick-Cli-Argv: {argv}\r\n"
        f"X-Maverick-Cli-Cwd: {cwd}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    connection.sendall(request)
    connection.sendall(stdin)
    stream = connection.makefile("rb", buffering=0)
    try:
        status_line = stream.readline(4097)
        if not status_line.startswith(b"HTTP/1.1 200 "):
            raise RuntimeError("Codex model bridge is unavailable")
        while True:
            line = stream.readline(65537)
            if not line or len(line) > 65536:
                raise RuntimeError("Codex model bridge response is invalid")
            if line in {b"\r\n", b"\n"}:
                break
        exit_code = 1
        while True:
            first = stream.read(1)
            if not first:
                break
            header = first + _read_exact(stream, 4)
            channel = header[:1]
            length = struct.unpack("!I", header[1:])[0]
            payload = _read_exact(stream, length)
            if channel == b"O":
                sys.stdout.buffer.write(payload)
                sys.stdout.buffer.flush()
            elif channel == b"E":
                sys.stderr.buffer.write(payload)
                sys.stderr.buffer.flush()
            elif channel == b"X":
                result = json.loads(payload)
                exit_code = int(result.get("exit_code", 1))
            else:
                raise RuntimeError("Codex model bridge channel is invalid")
        return exit_code
    finally:
        stream.close()
        connection.close()


def _configuration() -> tuple[Path, str]:
    if os.environ.get("MAVERICK_MODEL_ACCESS_STATE") != "available":
        raise RuntimeError("Codex model bridge is unavailable")
    socket_path = Path(os.environ.get("MAVERICK_MODEL_ACCESS_SOCKET", ""))
    token = os.environ.get("MAVERICK_MODEL_ACCESS_TOKEN", "")
    if socket_path != EXPECTED_SOCKET or not token or "\x00" in token:
        raise RuntimeError("Codex model bridge capability is invalid")
    return socket_path, token


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _validate_selected_model(
    arguments: tuple[str, ...],
    *,
    profile_path: Path = EXPECTED_PROFILE,
) -> None:
    """Keep direct CLI execution inside the workspace-scoped native catalog."""
    positions = [index for index, value in enumerate(arguments) if value == "--model"]
    if not positions:
        return
    if len(positions) != 1 or positions[0] + 1 >= len(arguments):
        raise RuntimeError("Codex model selection is invalid")
    selected = arguments[positions[0] + 1]
    try:
        metadata = profile_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("Codex model profile is unsafe")
        if metadata.st_size > MAX_PROFILE_BYTES:
            raise RuntimeError("Codex model profile is invalid")
        body = profile_path.read_bytes()
        if len(body) > MAX_PROFILE_BYTES:
            raise RuntimeError("Codex model profile is invalid")
        payload = json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Codex model profile is unavailable") from error
    agents = payload.get("agents") if isinstance(payload, dict) else None
    profiles: list[dict[str, object]] = []
    if isinstance(agents, list):
        profiles = [
            agent
            for agent in agents
            if isinstance(agent, dict) and agent.get("id") == CLI_PROFILE_ID
        ]
    if len(profiles) != 1:
        raise RuntimeError("Codex model profile is invalid")
    models = profiles[0].get("models")
    allowed: set[str] = set()
    if isinstance(models, list):
        allowed = {
            model["id"]
            for model in models
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        }
    if selected not in allowed:
        raise RuntimeError("Selected Codex model is unavailable in this workspace")


def _read_exact(stream, length: int) -> bytes:
    if length > MAX_STDIN_BYTES:
        raise RuntimeError("Codex model bridge frame is too large")
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise RuntimeError("Codex model bridge frame is incomplete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
