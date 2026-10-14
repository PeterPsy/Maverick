#!/usr/bin/env python3
"""Operator-managed wildcard issuance, renewal, validation and activation."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.shared.browser_origin_tls_backoff import (
    clear_issuance_backoff, issuance_retry_at, record_issuance_failure,
)
from core.shared.env_file import read_env_file, service_env_path
from core.installation.protected_material import require_service_environment
from core.shared.installation_material import certbot_root, certbot_directory_arguments, certbot_executable, validate_certbot_executable
from scripts.deploy.refresh_cloudflare_dns_credentials import DEFAULT_CREDENTIALS, refresh_credentials

CA = "https://acme-v02.api.letsencrypt.org/directory"


def verify_wildcard_https(hostname: str) -> None:
    """A fresh reserved origin must pass public CA and hostname verification."""
    host = "af-" + secrets.token_hex(12) + ".sidecars." + hostname
    context = ssl.create_default_context()
    for attempt in range(6):
        try:
            with socket.create_connection((host, 443), timeout=10) as connection:
                with context.wrap_socket(connection, server_hostname=host):
                    return
        except OSError:
            if attempt == 5:
                raise
            # Nginx processes SIGHUP asynchronously; allow the worker handover.
            time.sleep(1)


def certbot_command(hostname: str, email: str) -> list[str]:
    return [str(certbot_executable(ROOT)), "certonly", "--non-interactive", "--agree-tos",
            "--email", email, "--keep-until-expiring", "--no-directory-hooks",
            "--cert-name", hostname + "-sidecars-wildcard", "--dns-cloudflare",
            "--dns-cloudflare-credentials", str(DEFAULT_CREDENTIALS),
            "--dns-cloudflare-propagation-seconds", "60",
            "-d", "*.sidecars." + hostname,
            "--pre-hook", f"{ROOT}/.venv/bin/python {ROOT}/scripts/deploy/refresh_cloudflare_dns_credentials.py",
            "--deploy-hook", f"{ROOT}/.venv/bin/python {ROOT}/scripts/deploy/reload_nginx.py"] + certbot_directory_arguments(ROOT)


def maintain(hostname: str, email: str, nginx_config: Path, state_root: Path, *, runner=subprocess.run) -> dict:
    retry = issuance_retry_at(state_root, hostname, CA)
    if retry is not None and retry > datetime.now(timezone.utc):
        return {"status": "waiting", "retry_at": retry.isoformat()}
    validate_certbot_executable(ROOT)
    refresh_credentials(DEFAULT_CREDENTIALS)
    result = runner(certbot_command(hostname, email), capture_output=True, text=True, timeout=300)
    if result.returncode:
        failure = subprocess.CalledProcessError(result.returncode, ["certbot"],
                                               stderr=(result.stdout or "") + (result.stderr or ""))
        record_issuance_failure(state_root, hostname, CA, failure)
        retry = issuance_retry_at(state_root, hostname, CA)
        return {"status": "issuance_failed", "retry_at": retry.isoformat() if retry else None}
    clear_issuance_backoff(state_root, hostname, CA)
    verified = state_root / ("renewal-verified-" + hostname)
    if not verified.exists():
        renewal = runner([str(certbot_executable(ROOT)), "renew", "--non-interactive", "--dry-run",
                          "--no-random-sleep-on-renew",
                          "--no-directory-hooks", "--run-deploy-hooks",
                          "--cert-name", hostname + "-sidecars-wildcard"] + certbot_directory_arguments(ROOT),
                         capture_output=True, text=True, timeout=300)
        if renewal.returncode:
            return {"status": "renewal_verification_failed"}
        verified.touch(mode=0o600)
    if os.environ.get("LOOPINO_BROWSER_ORIGIN_TLS_MODE") != "external_wildcard":
        # Persist intent before the transition, including interruption recovery.
        (state_root / "restart-required").touch(mode=0o600)
    activation = runner([str(ROOT / ".venv/bin/python"),
                         str(ROOT / "scripts/deploy/activate_browser_origin_wildcard.py"),
                         "--hostname", hostname, "--certificate-dir",
                         str(certbot_root(ROOT) / "config/live" / (hostname + "-sidecars-wildcard")),
                         "--nginx-config", str(nginx_config), "--apply"],
                        capture_output=True, text=True, timeout=30)
    if activation.returncode:
        return {"status": "activation_failed"}
    activated = json.loads(activation.stdout)
    if activated.get("backend_restart_required"):
        (state_root / "restart-required").touch(mode=0o600)
    try:
        verify_wildcard_https(hostname)
    except OSError:
        return {"status": "wildcard_https_verification_failed"}
    return {"status": "active", "certificate": activated["certificate"],
            "renewal_verified": True, "wildcard_https_verified": True,
            "backend_restart_required": (state_root / "restart-required").exists()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--nginx-config", required=True, type=Path)
    parser.add_argument("--state-root", type=Path, default=ROOT / "data/wildcard-maintenance")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Root privileges are required")
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", args.hostname):
        parser.error("Use a canonical installation hostname")
    if any(character in str(ROOT) for character in " \t\n'\";$`"):
        parser.error("The installation path must be safe for Certbot hook commands")
    if not args.email or any(c.isspace() for c in args.email):
        parser.error("Use a notification email address without whitespace")
    for path in (args.state_root, args.nginx_config):
        if not path.is_absolute() or any(p.is_symlink() for p in path.parents):
            parser.error("Use absolute installation paths without symlink ancestors")
    args.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.state_root.chmod(0o700)
    environment_path = service_env_path(ROOT)
    require_service_environment(environment_path)
    os.environ.update(read_env_file(environment_path))
    os.chdir(ROOT)
    with (args.state_root / "maintenance.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "already_running"}))
            return 0
        try:
            result = maintain(args.hostname, args.email, args.nginx_config, args.state_root)
        except Exception as error:
            result = {"status": "blocked", "error_type": type(error).__name__}
        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        temporary = args.state_root / "status.json.tmp"
        temporary.write_text(json.dumps(result))
        temporary.chmod(0o600)
        temporary.replace(args.state_root / "status.json")
        print(json.dumps(result))
        return 0 if result["status"] in {"waiting", "active"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
