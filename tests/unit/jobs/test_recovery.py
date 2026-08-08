from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from core.api.backend_recovery import _recover_backend_restart
from core.api.platform_state import bootstrap_platform_state
from core.jobs.service import JobService
from tests.unit.jobs.support import FixedClock, make_executor, make_service, make_spec


class JobRecoveryIntegrationTestCase(unittest.TestCase):
    def test_backend_recovery_reconciles_expired_jobs(self) -> None:
        service, clock = make_service()
        service.advertise_executor(make_executor())
        submitted = service.submit(make_spec(with_output=False), job_id="job-one")
        service.lease(
            submitted.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=5,
        )
        clock.advance(seconds=6)

        with patch(
            "core.api.backend_recovery.recover_interrupted_runtime_turns_after_backend_restart",
            return_value={"recovered": 0},
        ) as runtime_recovery, patch(
            "core.api.backend_recovery.resume_recovering_orchestrations",
            return_value=[],
        ) as orchestration_recovery:
            _recover_backend_restart(SimpleNamespace(job_service=service))

        self.assertEqual(service.get("job-one", workspace_id="workspace-a").state, "queued")
        runtime_recovery.assert_called_once()
        orchestration_recovery.assert_called_once()

    def test_json_platform_bootstrap_recovers_persisted_expired_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = _repository_root(Path(temporary_directory))
            environment = {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
                "MAVERICK_CONTROL_STORE": "json",
                "MAVERICK_JSON_CONTROL_STORE_ROOT": str(repository_root / "data" / "control-plane" / "json"),
            }
            with patch.dict("os.environ", environment):
                state = bootstrap_platform_state(start_path=repository_root, install_builtin_apps=False)
                fixed_service = JobService(state.job_service.store, clock=FixedClock())
                fixed_service.advertise_executor(make_executor())
                submitted = fixed_service.submit(
                    replace(
                        make_spec(workspace_id="default", with_output=False),
                        input_grants=(),
                        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
                        budget=replace(
                            make_spec().budget,
                            max_runtime_seconds=31_536_000,
                        ),
                        timeout_seconds=None,
                    ),
                    job_id="job-one",
                )
                fixed_service.lease(
                    submitted.job_id,
                    workspace_id="default",
                    executor_id="executor-a",
                    lease_seconds=5,
                )
                restarted = bootstrap_platform_state(
                    start_path=repository_root,
                    install_builtin_apps=False,
                    recover_backend_restart=True,
                )
                recovered = restarted.job_service.get("job-one", workspace_id="default")

                self.assertEqual(recovered.state, "queued")
                self.assertIsNone(recovered.lease)
                self.assertEqual(recovered.attempt, 1)


def _repository_root(temporary_root: Path) -> Path:
    repository_root = temporary_root / "maverick"
    for name in ("core", "apps", "workspaces", "scripts", "docs"):
        (repository_root / name).mkdir(parents=True, exist_ok=True)
    (repository_root / "AGENTS.md").write_text("", encoding="utf-8")
    return repository_root


if __name__ == "__main__":
    unittest.main()
