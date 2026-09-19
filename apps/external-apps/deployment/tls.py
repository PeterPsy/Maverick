"""Operator-managed oneshot: bounded exact-host HTTP-01 issuance and renewal.

Install this file and tls_config.py root-owned, not as an app/backend entrypoint.
Never handles requests or imports Core. No hostname from the public listener can
trigger issuance. A fresh trusted supervisor projection is the sole request input.
"""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import time

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from tls_config import ACME_ROOT, TLS_ROOT, certificate_requests, installation_domain, read_json, render_hosts, valid_host


def atomic_text(path, value, mode=0o600):
    temporary = path.with_suffix(path.suffix + ".new")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode), "w") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def certificate(lineage, namespace, domain):
    """Reject mismatched, invalid or out-of-namespace material before nginx."""
    cert = x509.load_pem_x509_certificate((lineage / "fullchain.pem").read_bytes())
    key = serialization.load_pem_private_key((lineage / "privkey.pem").read_bytes(), password=None)
    encoding, format_ = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    if key.public_key().public_bytes(encoding, format_) != cert.public_key().public_bytes(encoding, format_):
        raise ValueError("tls_key_mismatch")
    hosts = set(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName))
    if not 1 <= len(hosts) <= 100 or any(
            host != domain if namespace == "base" else not valid_host(host, namespace, domain) for host in hosts):
        raise ValueError("invalid_certificate_names")
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise ValueError("invalid_certificate_dates")
    return hosts, cert.not_valid_after_utc > now + timedelta(days=30)


def certbot_command(lineage_name, hosts, root, webroot, acme_server=""):
    command = ["/usr/bin/certbot", "certonly", "--non-interactive", "--agree-tos",
               "--register-unsafely-without-email", "--no-eff-email", "--webroot", "--webroot-path", str(webroot),
               "--preferred-challenges", "http", "--config-dir", str(root / "config"),
               "--work-dir", str(root / "work"), "--logs-dir", str(root / "logs"),
               "--cert-name", lineage_name, "--key-type", "ecdsa", "--force-renewal"]
    if acme_server:
        command += ["--server", acme_server]
    for host in sorted(hosts):
        command += ["-d", host]
    return command


def refresh(requests, domain, *, root=TLS_ROOT, webroot=ACME_ROOT, acme_server="", runner=subprocess.run):
    """One SAN lineage per namespace (100-app cap); bounded attempts/backoff."""
    import json
    attempts_path = root / "attempts.json"
    attempts = read_json(attempts_path) if attempts_path.exists() else {}
    certificates, errors, issued = [], [], 0
    for namespace, requested in sorted(requests.items()):
        name = "maverick-external-" + hashlib.sha256(domain.encode()).hexdigest()[:12] + "-" + namespace
        lineage = root / "config/live" / name
        hosts, current = set(), False
        try:
            hosts, current = certificate(lineage, namespace, domain)
        except (OSError, ValueError, x509.ExtensionNotFound):
            pass
        desired = hosts | set(requested)
        if len(desired) > 100:
            raise ValueError("certificate_name_capacity")
        if not current or not set(requested) <= hosts:
            if issued < 4 and attempts.get(name, 0) <= time.time():
                # Persist before invoking ACME: killed jobs cannot busy-retry.
                attempts[name] = time.time() + 3600
                atomic_text(attempts_path, json.dumps(attempts))
                atomic_text(root / "reload.pending", "pending\n")
                issued += 1
                try:
                    runner(certbot_command(name, desired, root, webroot, acme_server),
                           check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    hosts, current = certificate(lineage, namespace, domain)
                    if not current or not desired <= hosts:
                        raise ValueError("incomplete_certificate")
                    attempts[name] = time.time() + 120
                    atomic_text(attempts_path, json.dumps(attempts))
                except (OSError, ValueError, subprocess.SubprocessError, x509.ExtensionNotFound):
                    errors.append(namespace)
        if hosts:
            certificates.append((hosts, lineage))
    return certificates, errors


def activate(contents, *, root=TLS_ROOT, runner=subprocess.run):
    path = root / "hosts.conf"
    previous = path.read_text() if path.exists() else ""
    pending = root / "reload.pending"
    if contents == previous and not pending.exists():
        return
    atomic_text(pending, "pending\n")
    atomic_text(path, contents, 0o644)
    try:
        runner(["/usr/sbin/nginx", "-t"], check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        runner(["/usr/bin/systemctl", "reload", "nginx"], check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (OSError, subprocess.SubprocessError) as error:
        atomic_text(path, previous, 0o644)
        diagnostic = getattr(error, "stderr", None) or str(error).encode()
        atomic_text(root / "nginx-error.log", diagnostic.decode(errors="replace")[:16384])
        raise
    pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/maverick/external-apps.json")
    args = parser.parse_args()
    config = read_json(Path(args.config), 16384)
    domain = installation_domain(config["installation_domain"])
    projection = read_json(Path(config["state_directory"]) / "mounts.json")
    requests = certificate_requests(projection, domain)
    TLS_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    ACME_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    with (TLS_ROOT / "issuance.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        certificates, errors = refresh(requests, domain)
        activate(render_hosts(certificates))
        if errors:
            raise RuntimeError("certificate_issuance_failed: " + ",".join(errors))


if __name__ == "__main__":
    main()
