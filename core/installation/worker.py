"""Durable host worker: bootstrap, resume, verify, activate and roll back."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.request import Request, build_opener
from uuid import uuid4

from core.installation.certificates import prepare_certificates, certificate_names, certificate_paths
from core.installation.cloudflare import NoRedirect
from core.installation.dns_propagation import dns_ready
from core.installation.private_state import write_private
from core.installation.dns_transaction import apply_dns, restore_dns
from core.installation.errors import InstallationError
from core.installation.host_configuration import stage_host, commit_environment, restore_host
from core.installation.probes import https_probe, verify_web
from core.installation.service import ACTIVE_STATES, timestamp, digest
from core.installation.validation import public_ip, hostname, secret_ref, record_id


def discover_public_ip() -> str:
    try:
        with build_opener(NoRedirect).open(Request("https://www.cloudflare.com/cdn-cgi/trace"), timeout=5) as response:
            content = response.read(4096).decode()
        match = re.search(r"^ip=(.+)$", content, re.MULTILINE)
        return public_ip(match.group(1)) if match else ""
    except (OSError, ValueError):
        return ""


class InstallationWorker:
    def __init__(self, service, *, dns=apply_dns, certificates=prepare_certificates,
                 stage=stage_host, commit=commit_environment, verify=verify_web, probe=https_probe,
                 restore=restore_host, dns_restore=restore_dns, propagation=dns_ready):
        self.service, self.store = service, service.store
        self.dns, self.certificates, self.stage, self.commit = dns, certificates, stage, commit
        self.verify, self.probe, self.restore, self.dns_restore = verify, probe, restore, dns_restore
        self.propagation = propagation

    def tick(self) -> dict:
        with self.store.locked():
            if not self.store.read("configuration"):
                configuration = self.service.configuration()
                configuration.update(installation_id=uuid4().hex, generation=0)
                self.store.write("configuration", configuration)
        previous = self.store.read("worker") or {}
        worker = {**previous, "state": "online", "checked_at": timestamp(),
                  "public_ip": previous.get("public_ip") or discover_public_ip()}
        self.store.write("worker", worker)
        jobs = [job for job in reversed(self.store.list_jobs()) if job["status"] in ACTIVE_STATES]
        if jobs:
            job = jobs[0]
            retry = job.get("retry_at")
            if retry and datetime.fromisoformat(retry) > datetime.now(timezone.utc):
                return job
            try:
                return self.rollback(job) if job["operation"] == "rollback" else self.advance(job)
            except Exception as error:
                job.update(status="failed", error_code=error.code if isinstance(error, InstallationError) else "host_operation_failed",
                           error_type=type(error).__name__, updated_at=timestamp())
                self.store.write("jobs", job, job["job_id"])
                return job
        configuration = self.service.configuration()
        if configuration.get("managed"):
            self.renew(configuration, worker)
        if configuration.get("hostname") and worker["public_ip"]:
            worker["verification"] = self.verify(configuration["hostname"], configuration.get("target_ip") or worker["public_ip"])
            worker["state"] = "healthy" if worker["verification"]["healthy"] else "needs_attention"
            self.store.write("worker", worker)
        return worker

    def renew(self, configuration, worker):
        """Check expiry locally; renew only in the certificate's renewal window."""
        from cryptography import x509
        now = datetime.now(timezone.utc)
        previous = self.store.read("worker") or {}
        checked = previous.get("renewal_checked_at")
        if checked and now - datetime.fromisoformat(checked) < timedelta(hours=6):
            worker["renewal_checked_at"] = checked
            return
        worker["renewal_checked_at"] = timestamp()
        paths = configuration.get("certificates") or certificate_paths(certificate_names(configuration["hostname"]))
        try:
            due = any(x509.load_pem_x509_certificate(Path(pair["fullchain"]).read_bytes()).not_valid_after_utc
                      - now < timedelta(days=30) for pair in paths.values())
            if not due:
                worker["renewal_state"] = "scheduled"
                return
            job_id = configuration["activated_by_job"]
            job = self.store.read("jobs", job_id)
            plan = self.store.read("plans", job["plan_id"])
            private = self.store.root / "private" / job_id
            result = self.certificates(self.service, job, plan, private)
            worker["renewal_state"] = "waiting_ca" if result["waiting"] else "verified"
            worker["renewal_retry_at"] = result.get("retry_at")
        except Exception as error:
            worker["renewal_state"] = "failed"
            worker["renewal_error_type"] = type(error).__name__

    def advance(self, job: dict) -> dict:
        plan = self.store.read("plans", job["plan_id"])
        self.validate_job(job, plan)
        private = self.store.root / "private" / job["job_id"]
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        if job["step"] == "restarting":
            try:
                proof = self.probe(plan["hostname"], plan["target_ip"], "/api/installation/probe/" + job["job_id"])
            except (OSError, ValueError):
                return self.wait(job, "verifying", seconds=30)
            if proof.get("proof", {}).get("hostname") != plan["hostname"]:
                return self.wait(job, "verifying", seconds=30)
            result = self.verify(plan["hostname"], plan["target_ip"])
            if not result["healthy"]:
                return self.wait(job, "verifying", seconds=30)
            job.update(status="ready", step="ready", verification=result, finished_at=timestamp(), updated_at=timestamp())
            return self.store.write("jobs", job, job["job_id"])
        intent = private / "activation.json"
        if intent.exists():
            return self.activate(job, plan, private, json.loads(intent.read_text()))
        self.save_step(job, "preparing")
        dns = self.dns(self.service, job, plan, private)
        if dns["waiting"]:
            return self.wait(job, "waiting_dns", seconds=60)
        if not self.propagation(plan["hostname"], plan["target_ip"]):
            return self.wait(job, "waiting_dns", seconds=60)
        certificate = self.certificates(self.service, job, plan, private)
        if certificate["waiting"]:
            return self.wait(job, "waiting_ca", retry_at=certificate.get("retry_at"), seconds=300)
        self.stage(self.service, plan, certificate["certificates"], private)
        proof = self.probe(plan["hostname"], plan["target_ip"], "/api/installation/probe/" + job["job_id"])
        if proof.get("proof", {}).get("nonce") != job["probe_nonce"]:
            raise InstallationError("wrong_server_at_target_address", status=409)
        required = {item["id"] for item in plan["external_actions"]}
        if required - set(job["confirmed_actions"]):
            return self.wait(job, "waiting_external_actions", seconds=60)
        self.save_step(job, "activating")
        previous = self.service.configuration()
        configuration = {"installation_id": previous["installation_id"], "generation": previous["generation"] + 1,
            **{key: plan[key] for key in ("hostname", "public_url", "target_ip", "dns_provider", "dns_secret_ref")},
            "managed": True, "tls_mode": "external_wildcard", "certificates": certificate["certificates"],
            "renewal_verified": True, "activated_by_job": job["job_id"], "updated_at": timestamp()}
        write_private(private / "activation.json", configuration)
        return self.activate(job, plan, private, configuration)

    def activate(self, job, plan, private, configuration):
        current = self.service.configuration()
        if current["generation"] != plan["generation"] and current.get("activated_by_job") != job["job_id"]:
            raise InstallationError("stale_installation_plan", status=409)
        if self.store.read("jobs", job["job_id"])["status"] == "rollback_requested":
            raise InstallationError("installation_change_cancelled", status=409)
        self.commit(self.service, plan, private)
        # The root-owned intent repairs crashes between environment write,
        # configuration publication and job publication without incrementing twice.
        marker = self.store.root / "private" / "restart-required"
        marker.write_text(job["job_id"])
        marker.chmod(0o600)
        with self.store.locked():
            self.store.write("configuration", configuration)
            job.update(status="verifying", step="restarting", activated_generation=configuration["generation"], updated_at=timestamp())
            self.store.write("jobs", job, job["job_id"])
        return job

    def validate_job(self, job, plan):
        record_id(job["job_id"])
        record_id(plan["plan_id"])
        hostname(plan["hostname"])
        public_ip(plan["target_ip"])
        secret_ref(plan["dns_secret_ref"])
        if digest({key: value for key, value in plan.items() if key != "fingerprint"}) != plan["fingerprint"]:
            raise InstallationError("plan_integrity_failed", status=409)
        current = self.service.configuration()
        if current["generation"] != plan["generation"] and current.get("activated_by_job") != job["job_id"]:
            raise InstallationError("stale_installation_plan", status=409)

    def rollback(self, job: dict) -> dict:
        original = self.store.read("jobs", job["rollback_of"])
        plan = self.store.read("plans", original["plan_id"])
        configuration = self.service.configuration()
        if job["step"] == "rollback_restarting":
            if (self.store.root / "private" / "restart-required").exists():
                return self.wait(job, "rolling_back", seconds=30)
            if configuration["hostname"]:
                result = self.verify(configuration["hostname"], configuration.get("target_ip") or plan["target_ip"])
                if not result["healthy"]:
                    return self.wait(job, "rolling_back", seconds=30)
                job["verification"] = result
            job.update(status="rolled_back", step="rolled_back", updated_at=timestamp())
            return self.store.write("jobs", job, job["job_id"])
        rollback_private = self.store.root / "private" / job["job_id"]
        intent = rollback_private / "rollback.json"
        if intent.exists():
            restored = json.loads(intent.read_text())
            if configuration["generation"] != restored["generation"] and configuration["generation"] != restored["generation"] - 1:
                raise InstallationError("stale_installation_rollback", status=409)
        else:
            expected = original.get("activated_generation", plan["generation"])
            if configuration["generation"] != expected:
                raise InstallationError("stale_installation_rollback", status=409)
            private = self.store.root / "private" / original["job_id"]
            self.dns_restore(self.service, original, plan, private)
            self.restore(self.service, private)
            restored = {**plan["previous"], "generation": configuration["generation"] + 1,
                        "installation_id": configuration["installation_id"], "updated_at": timestamp()}
            write_private(intent, restored)
        marker = self.store.root / "private" / "restart-required"
        marker.write_text(job["job_id"])
        marker.chmod(0o600)
        with self.store.locked():
            self.store.write("configuration", restored)
            job.update(status="rolling_back", step="rollback_restarting", updated_at=timestamp())
            return self.store.write("jobs", job, job["job_id"])

    def save_step(self, job, step):
        job.update(status=step, step=step, updated_at=timestamp())
        job["events"] = (job.get("events", []) + [{"step": step, "at": job["updated_at"]}])[-100:]
        self.store.write("jobs", job, job["job_id"])

    def wait(self, job, status, *, seconds=60, retry_at=None):
        retry = retry_at or (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        job.update(status=status, retry_at=retry, updated_at=timestamp())
        return self.store.write("jobs", job, job["job_id"])
