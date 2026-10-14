"""Root-owned Certbot delivery, issuance and staging renewal verification."""

from datetime import datetime, timezone
from pathlib import Path
import shlex
import subprocess

from core.installation.errors import InstallationError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.shared.browser_origin_tls_backoff import issuance_retry_at, record_issuance_failure, clear_issuance_backoff
from core.shared.installation_material import certbot_root, certbot_directory_arguments, dns_credentials_root, certbot_executable, validate_certbot_executable
from scripts.deploy.refresh_cloudflare_dns_credentials import refresh_credentials

CA = "https://acme-v02.api.letsencrypt.org/directory"


def certificate_names(host: str) -> dict:
    return {"main": host, "apps": host + "-sidecars-wildcard"}


def certificate_paths(names: dict, *, repository_root: Path) -> dict:
    live = certbot_root(repository_root) / "config/live"
    return {kind: {"cert_name": name, "fullchain": str(live / name / "fullchain.pem"),
                   "private_key": str(live / name / "privkey.pem")} for kind, name in names.items()}


def prepare_certificates(service, job: dict, plan: dict, private: Path, *, runner=subprocess.run) -> dict:
    retry = issuance_retry_at(private, plan["hostname"], CA)
    if retry and retry > datetime.now(timezone.utc):
        return {"waiting": True, "retry_at": retry.isoformat()}
    root = service.store.repository_root
    validate_certbot_executable(root)
    credentials = dns_credentials_root(root) / ("installation-" + job["job_id"] + ".ini")
    reference = plan["dns_secret_ref"]
    def resolve():
        return resolve_secret_for_runtime(service.secret_store, secret_ref=reference,
            context=SecretResolutionContext(workspace_id=None, operator_request=True,
                platform_delivery=True, allow_unbound_secret_refs=True,
                actor_user_id=job["actor_user_id"], action="installation.tls.dns01",
                target="https://api.cloudflare.com/client/v4/")).value
    refresh_credentials(credentials, resolver=resolve)
    hook = shlex.join([str(root / ".venv/bin/python"),
        str(root / "scripts/deploy/refresh_cloudflare_dns_credentials.py"),
        "--secret-ref", reference, "--credentials", str(credentials)])
    reload_hook = shlex.join([str(root / ".venv/bin/python"), str(root / "scripts/deploy/reload_nginx.py")])
    paths = certificate_paths(certificate_names(plan["hostname"]), repository_root=root)
    for kind, identifier in [("main", plan["hostname"]), ("apps", "*.sidecars." + plan["hostname"])]:
        command = [str(certbot_executable(root)), "certonly", "--non-interactive", "--agree-tos",
            "--register-unsafely-without-email", "--keep-until-expiring", "--no-directory-hooks",
            "--cert-name", paths[kind]["cert_name"], "--dns-cloudflare",
            "--dns-cloudflare-credentials", str(credentials), "--dns-cloudflare-propagation-seconds", "60",
            "--pre-hook", hook, "--deploy-hook", reload_hook, "-d", identifier] + certbot_directory_arguments(root)
        result = runner(command, capture_output=True, text=True, timeout=300)
        if result.returncode:
            error = subprocess.CalledProcessError(result.returncode, ["certbot"],
                stderr=(result.stdout or "") + (result.stderr or ""))
            record_issuance_failure(private, plan["hostname"], CA, error)
            retry = issuance_retry_at(private, plan["hostname"], CA)
            return {"waiting": True, "retry_at": retry.isoformat() if retry else None}
        verified = private / ("renewal-verified-" + kind)
        if not verified.exists():
            result = runner([str(certbot_executable(root)), "renew", "--dry-run", "--non-interactive",
                "--no-random-sleep-on-renew", "--no-directory-hooks", "--cert-name", paths[kind]["cert_name"],
                "--dns-cloudflare", "--dns-cloudflare-credentials", str(credentials), "--pre-hook", hook,
                "--deploy-hook", reload_hook, "--run-deploy-hooks"] + certbot_directory_arguments(root), capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise InstallationError("renewal_verification_failed", status=502)
            verified.touch(mode=0o600)
    clear_issuance_backoff(private, plan["hostname"], CA)
    return {"waiting": False, "certificates": paths, "renewal_verified": True}
