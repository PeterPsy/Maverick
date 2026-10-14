#!/usr/bin/env python3
"""Run one bounded host-infrastructure tick. Output is metadata only."""

import fcntl
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.installation.service import InstallationService
from core.installation.worker import InstallationWorker
from core.secrets.store import SecretDocumentStore
from core.shared.env_file import read_env_file, service_env_path
from core.installation.protected_material import require_service_environment


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "root_required"}))
        return 1
    try:
        environment_path = service_env_path(ROOT)
        require_service_environment(environment_path)
        os.environ.update(read_env_file(environment_path))
        collections = build_control_plane_collections(ControlStoreSettings.from_environment(repository_root=ROOT))
        service = InstallationService(ROOT, secret_store=SecretDocumentStore(collections.secrets))
        private = service.store.root / "private"
        service.store._safe(private)
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        private.chmod(0o700)
        with (private / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = InstallationWorker(service).tick()
        print(json.dumps({"status": result.get("status", result.get("state")), "job_id": result.get("job_id"),
                          "error_code": result.get("error_code")}))
        return 0
    except BlockingIOError:
        return 0
    except Exception as error:
        print(json.dumps({"error": "installation_worker_failed", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
