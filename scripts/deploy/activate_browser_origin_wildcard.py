#!/usr/bin/env python3
"""Switch an existing installation to verified wildcard TLS without reinstalling it."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.shared.installer_tls import hosted_sidecar_tls_errors
from scripts.deploy.reload_nginx import check_nginx, reload_nginx


def external_tls_environment(content: str) -> str:
    """Preserve every unrelated setting, comment and credential byte."""
    pattern = re.compile(r"^(?:export\s+)?MAVERICK_BROWSER_ORIGIN_TLS_MODE\s*=")
    lines = content.splitlines(keepends=True)
    found = False
    output = []
    for line in lines:
        if pattern.match(line):
            if not found:
                output.append("MAVERICK_BROWSER_ORIGIN_TLS_MODE=external_wildcard\n")
                found = True
        else:
            output.append(line)
    if not found:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.append("MAVERICK_BROWSER_ORIGIN_TLS_MODE=external_wildcard\n")
    return "".join(output)


def atomic_replace(path: Path, data: bytes) -> None:
    metadata = path.stat()
    handle, temporary = tempfile.mkstemp(prefix=".wildcard-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, metadata.st_mode & 0o777)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply_transition(nginx_path: Path, env_path: Path, nginx_content: str, *, tester=check_nginx, reloader=reload_nginx) -> None:
    """Test before reload and restore both files if a step fails."""
    original_nginx = nginx_path.read_bytes()
    original_env = env_path.read_bytes()
    next_env = external_tls_environment(original_env.decode()).encode()
    try:
        atomic_replace(nginx_path, nginx_content.encode())
        tester()
        atomic_replace(env_path, next_env)
        reloader()
    except BaseException:
        atomic_replace(nginx_path, original_nginx)
        atomic_replace(env_path, original_env)
        reloader()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--certificate-dir", type=Path, required=True)
    parser.add_argument("--nginx-config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", args.hostname):
        parser.error("Use a canonical installation hostname.")
    certificate = args.certificate_dir / "fullchain.pem"
    key = args.certificate_dir / "privkey.pem"
    if not args.certificate_dir.is_absolute() or any(c in str(args.certificate_dir) for c in '\"\\;\n\r{} '):
        parser.error("Use an absolute certificate directory without nginx control characters.")
    errors = hosted_sidecar_tls_errors(hostname=args.hostname,
        certificate_path_value=str(certificate), private_key_path_value=str(key))
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}))
        return 1
    content = (ROOT / "scripts/deploy/nginx/maverick.sidecars.example.conf").read_text()
    for placeholder, value in {
        "{{HOSTNAME}}": args.hostname, "{{SIDECAR_TLS_CERT_PATH}}": str(certificate),
        "{{SIDECAR_TLS_CERT_KEY_PATH}}": str(key), "{{BIND_HOST}}": "127.0.0.1", "{{CORE_PORT}}": "8014",
    }.items():
        content = content.replace(placeholder, value)
    if "{{" in content:
        raise RuntimeError("Unresolved nginx template placeholder")
    if args.apply:
        if os.geteuid() != 0:
            parser.error("Apply requires root privileges for nginx configuration.")
        nginx_path, env_path = args.nginx_config.resolve(strict=True), args.env_file.resolve(strict=True)
        environment_changed = external_tls_environment(env_path.read_text()).encode() != env_path.read_bytes()
        if not environment_changed and nginx_path.read_text() == content:
            print(json.dumps({"status": "already_active", "mode": "external_wildcard",
                "certificate": str(certificate), "backend_restart_required": False}))
            return 0
        backup = Path("/var/backups/maverick-wildcard") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup.mkdir(parents=True, mode=0o700)
        for source, name in [(nginx_path, "sidecars.conf"), (env_path, "installation.env")]:
            destination = backup / name
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o600)
        apply_transition(nginx_path, env_path, content)
    print(json.dumps({"status": "applied" if args.apply else "ready", "mode": "external_wildcard",
        "certificate": str(certificate), "backend_restart_required": bool(args.apply and environment_changed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
