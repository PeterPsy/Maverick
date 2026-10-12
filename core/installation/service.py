"""Administrative planning and durable job submission; no privileged shell work."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from core.installation.cloudflare import CloudflareDns, dns_changes, token_template
from core.installation.errors import InstallationError
from core.installation.store import InstallationStore
from core.installation.validation import hostname, public_ip, secret_ref
from core.secrets.errors import SecretError
from core.shared.env_file import read_env_file

ACTIVE_STATES = {"queued", "preparing", "waiting_dns", "waiting_ca", "waiting_external_actions", "activating", "verifying", "rolling_back"}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class InstallationService:
    def __init__(self, repository_root: Path, *, secret_store=None, app_store=None,
                 workspace_store=None, environment=None, dns_factory=CloudflareDns):
        self.store = InstallationStore(repository_root)
        self.secret_store, self.app_store, self.workspace_store = secret_store, app_store, workspace_store
        self.environment = environment if environment is not None else {**read_env_file(repository_root / ".env"), **os.environ}
        self.dns_factory = dns_factory

    def configuration(self) -> dict:
        configured = self.store.read("configuration")
        if configured:
            return configured
        host = self.environment.get("MAVERICK_SIDECAR_INSTALLATION_DOMAIN", "").strip()
        return {"installation_id": "uninitialized", "generation": 0,
                "hostname": host, "public_url": "https://" + host if host else "",
                "target_ip": self.environment.get("MAVERICK_INSTALLATION_PUBLIC_IP", ""),
                "dns_provider": "cloudflare", "dns_secret_ref": "platform:secret-alias/cloudflare-dns-api-token",
                "tls_mode": self.environment.get("MAVERICK_BROWSER_ORIGIN_TLS_MODE", ""),
                "managed": False}

    def inspect(self) -> dict:
        configuration = self.configuration()
        credentials = []
        if self.secret_store:
            for item in self.secret_store.list_secrets():
                if item.status == "active" and item.kind == "api_key" and "cloudflare" in (str(item.alias) + item.label).lower():
                    credentials.append({"label": item.label, "ref": "platform:secrets/" + item.secret_id})
        jobs = self.store.list_jobs()
        worker = self.store.read("worker") or {}
        setup_required = not configuration["hostname"] or not (configuration.get("managed") or worker.get("verification", {}).get("healthy"))
        return {"configuration": configuration, "dns_credentials": credentials,
                "setup_required": setup_required,
                "worker": self.store.read("worker"), "latest_job": jobs[0] if jobs else None,
                "requirements": self.requirements(configuration.get("hostname", "")),
                "configured": bool(configuration["hostname"]),
                "setup_url": "/setup", "providers": [{"id": "cloudflare", "automatic": True}, {"id": "manual", "automatic": False}]}

    def requirements(self, host: str) -> list[dict]:
        requirements = []
        env = self.environment
        def ready(reference):
            if not self.secret_store:
                return False
            try:
                kind, identifier = reference.split("/", 1)
                item = (self.secret_store.get_secret_by_alias(identifier) if kind == "platform:secret-alias"
                        else self.secret_store.get_secret(identifier))
                return item.status == "active"
            except (ValueError, KeyError, SecretError):
                return False
        references = [env.get("MAVERICK_GOOGLE_CLIENT_ID_REF", "platform:secret-alias/google-oauth-client-id"),
                      env.get("MAVERICK_GOOGLE_CLIENT_SECRET_REF", "platform:secret-alias/google-oauth-client-secret")]
        configured_google = all(ready(reference) for reference in references)
        requirements.append({"id": "core.google", "label": "Google · Calendar, Mail & Drive", "kind": "oauth_redirect",
            "url": "https://" + host + "/api/auth/google/callback" if host else "",
            "current_url": env.get("MAVERICK_GOOGLE_REDIRECT_URI", ""),
            "provider_url": "https://console.cloud.google.com/auth/clients", "configured": configured_google,
            "state": "configured" if configured_google else "connection_required"})
        if self.app_store and self.workspace_store:
            seen = set()
            for workspace in self.workspace_store.list_workspaces():
                if workspace.status != "active":
                    continue
                for binding in self.app_store.list_workspace_app_bindings(workspace.workspace_id):
                    key = (binding.app_id, binding.source_record_id)
                    if binding.status != "enabled" or key in seen:
                        continue
                    seen.add(key)
                    from core.apps.surfaces import resolve_workspace_app_surface
                    _, parsed = resolve_workspace_app_surface(self.app_store, binding=binding, start_path=self.store.repository_root)
                    declaration = getattr(parsed.contract, "installation", None)
                    for endpoint in declaration.public_endpoints if declaration else []:
                        requirements.append({"id": workspace.workspace_id + "." + binding.app_id + "." + endpoint.endpoint_id,
                            "label": endpoint.label + " · " + workspace.name, "app_id": binding.app_id, "kind": endpoint.kind,
                            "url": "https://" + host + endpoint.path.replace("{app_id}", binding.app_id) if host else "",
                            "provider_url": endpoint.provider_url, "configured": endpoint.requires_registration})
        return requirements

    def plan(self, *, address: str, target_ip: str, dns_provider="cloudflare",
             dns_secret_ref="platform:secret-alias/cloudflare-dns-api-token", actor_user_id=None) -> dict:
        host, address_ip = hostname(address), public_ip(target_ip)
        if dns_provider not in {"cloudflare", "manual"}:
            raise InstallationError("unsupported_dns_provider")
        current = self.configuration()
        zone, records, problems = None, [], []
        if dns_provider == "cloudflare":
            reference = secret_ref(dns_secret_ref)
            provider = self.dns_factory(self.secret_store, reference, actor_user_id=actor_user_id)
            zone = provider.zone(host)
            records = provider.records(zone["id"])
            if zone["status"] != "active":
                problems.append({"code": "dns_delegation_pending", "nameservers": zone["name_servers"]})
        else:
            reference = ""
            problems.append({"code": "dns_automation_connection_required"})
        requirements = self.requirements(host)
        actions = [{**item, "code": "update_provider_registration"} for item in requirements
                   if item.get("configured") and (host != current["hostname"]
                       or ("current_url" in item and item["current_url"] != item["url"]))]
        plan = {"plan_id": uuid4().hex, "created_at": timestamp(), "created_by": actor_user_id,
                "generation": current["generation"], "previous": current,
                "hostname": host, "public_url": "https://" + host, "target_ip": address_ip,
                "dns_provider": dns_provider, "dns_secret_ref": reference,
                "zone": zone, "dns_changes": dns_changes(host, address_ip, records),
                "certificate_names": [host, "*.sidecars." + host],
                "requirements": requirements, "external_actions": actions,
                "blocking_issues": problems,
                "token_template_url": token_template(zone) if zone else None,
                "change_kind": "server_move" if host == current["hostname"] else "address_change"}
        plan["fingerprint"] = digest(plan)
        with self.store.locked():
            self.store.write("plans", plan, plan["plan_id"])
        return plan

    def apply(self, plan_id: str, *, actor_user_id=None, confirmed_actions=None) -> dict:
        with self.store.locked():
            plan = self.store.read("plans", plan_id)
            if not plan:
                raise InstallationError("plan_not_found", status=404)
            if digest({key: value for key, value in plan.items() if key != "fingerprint"}) != plan["fingerprint"]:
                raise InstallationError("plan_integrity_failed", status=409)
            jobs = self.store.list_jobs()
            existing = next((job for job in jobs if job["plan_id"] == plan_id and job["operation"] == "apply"), None)
            if existing:
                return existing
            if plan["generation"] != self.configuration()["generation"]:
                raise InstallationError("stale_installation_plan", status=409)
            if plan["dns_provider"] == "manual":
                raise InstallationError("dns_automation_connection_required", status=409)
            if any(job["status"] in ACTIVE_STATES for job in jobs):
                raise InstallationError("installation_change_in_progress", status=409)
            confirmed = self._confirmed(plan, confirmed_actions or [])
            job = {"job_id": uuid4().hex, "plan_id": plan_id, "operation": "apply", "status": "queued",
                "created_at": timestamp(), "updated_at": timestamp(), "actor_user_id": actor_user_id,
                "confirmed_actions": confirmed, "probe_nonce": uuid4().hex, "step": "queued", "events": []}
            self.store.write("jobs", job, job["job_id"])
            return job

    def status(self, job_id: str) -> dict:
        job = self.store.read("jobs", job_id)
        if not job:
            raise InstallationError("job_not_found", status=404)
        return {"job": job, "plan": self.store.read("plans", job["plan_id"])}

    def confirm(self, job_id: str, action_ids: list[str], *, actor_user_id=None) -> dict:
        with self.store.locked():
            job = self.status(job_id)["job"]
            plan = self.store.read("plans", job["plan_id"])
            job["confirmed_actions"] = self._confirmed(plan, action_ids)
            job["confirmed_by"] = actor_user_id
            job["updated_at"] = timestamp()
            if job["status"] == "waiting_external_actions":
                job["status"] = "queued"
                job.pop("retry_at", None)
            return self.store.write("jobs", job, job_id)

    def verify(self) -> dict:
        from core.installation.probes import verify_web
        configuration = self.configuration()
        worker = self.store.read("worker") or {}
        address = configuration.get("target_ip") or worker.get("public_ip")
        if not configuration["hostname"] or not address:
            raise InstallationError("installation_address_not_configured", status=409)
        return {"configuration": configuration, "verification": verify_web(configuration["hostname"], address),
                "requirements": self.requirements(configuration["hostname"]), "checked_at": timestamp()}

    def retry(self, job_id: str, *, actor_user_id=None) -> dict:
        with self.store.locked():
            job = self.status(job_id)["job"]
            if job["status"] in ACTIVE_STATES or job["status"] in {"ready", "rolled_back"}:
                return job
            plan = self.store.read("plans", job["plan_id"])
            expected = job.get("activated_generation", plan["generation"])
            if self.configuration()["generation"] != expected:
                raise InstallationError("stale_installation_plan", status=409)
            if any(other["status"] in ACTIVE_STATES and other["job_id"] != job_id for other in self.store.list_jobs()):
                raise InstallationError("installation_change_in_progress", status=409)
            job.update(status="queued", updated_at=timestamp(), retried_by=actor_user_id)
            job.pop("retry_at", None)
            job.pop("error_code", None)
            return self.store.write("jobs", job, job_id)

    def rollback(self, job_id: str, *, actor_user_id=None) -> dict:
        with self.store.locked():
            original = self.status(job_id)["job"]
            if original["operation"] != "apply":
                raise InstallationError("apply_job_required")
            plan = self.store.read("plans", original["plan_id"])
            if self.configuration()["generation"] != original.get("activated_generation", plan["generation"]):
                raise InstallationError("stale_installation_rollback", status=409)
            existing = next((job for job in self.store.list_jobs() if job.get("rollback_of") == job_id), None)
            if existing:
                return existing
            active = [job for job in self.store.list_jobs() if job["status"] in ACTIVE_STATES and job["job_id"] != job_id]
            if active:
                raise InstallationError("installation_change_in_progress", status=409)
            original["status"] = "rollback_requested"
            self.store.write("jobs", original, job_id)
            job = {"job_id": uuid4().hex, "plan_id": original["plan_id"], "operation": "rollback",
                   "rollback_of": job_id, "probe_nonce": uuid4().hex, "status": "queued", "step": "queued", "created_at": timestamp(),
                   "updated_at": timestamp(), "actor_user_id": actor_user_id, "events": []}
            return self.store.write("jobs", job, job["job_id"])

    @staticmethod
    def _confirmed(plan, values):
        known = {item["id"] for item in plan["external_actions"]}
        if not isinstance(values, list) or any(not isinstance(item, str) or item not in known for item in values):
            raise InstallationError("invalid_external_action_confirmation")
        return sorted(set(values))
