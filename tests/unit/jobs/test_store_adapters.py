from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.jobs.errors import JobIdempotencyConflictError
from core.jobs.store import JobCollections, JobDocumentStore
from core.jobs.service import JobService
from core.shared.json_file_collection import JsonFileCollection
from core.shared.mongo_document_collection import MongoDocumentCollection
from tests.unit.shared.test_mongo_document_collection import FakeMongoCollection
from tests.unit.jobs.support import FixedClock, changed_spec, make_spec


def json_store(root: Path) -> JobDocumentStore:
    return JobDocumentStore(
        JobCollections(
            jobs=JsonFileCollection(root / "jobs.json"),
            events=JsonFileCollection(root / "events.json"),
            audits=JsonFileCollection(root / "audits.json"),
            logs=JsonFileCollection(root / "logs.json"),
            executors=JsonFileCollection(root / "executors.json"),
            quotas=JsonFileCollection(root / "quotas.json"),
        )
    )


def service_for(store: JobDocumentStore) -> JobService:
    service = JobService(store, clock=FixedClock())
    service.register_input_validator("file.content.read", lambda _spec, _grant: True)
    return service


class JobStoreAdapterTestCase(unittest.TestCase):
    def test_json_store_survives_service_restart_and_preserves_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_service = service_for(json_store(root))
            submitted = first_service.submit(make_spec(), job_id="job-one")

            restarted_service = service_for(json_store(root))
            loaded = restarted_service.get(submitted.job_id, workspace_id="workspace-a")
            replay = restarted_service.submit(make_spec(), job_id="ignored")

            self.assertEqual(loaded, submitted)
            self.assertEqual(replay.job_id, submitted.job_id)
            self.assertEqual(len(restarted_service.list_events("job-one", workspace_id="workspace-a")), 1)

    def test_mongo_document_adapter_preserves_job_idempotency_and_events(self) -> None:
        def collection():
            return MongoDocumentCollection(FakeMongoCollection())

        collections = JobCollections(
            jobs=collection(),
            events=collection(),
            audits=collection(),
            logs=collection(),
            executors=collection(),
            quotas=collection(),
        )
        service = service_for(JobDocumentStore(collections))

        submitted = service.submit(make_spec(), job_id="job-one")
        restarted_service = service_for(JobDocumentStore(collections))
        replay = restarted_service.submit(make_spec(), job_id="ignored")

        self.assertEqual(replay.job_id, submitted.job_id)
        self.assertEqual(restarted_service.get("job-one", workspace_id="workspace-a"), submitted)
        self.assertEqual(len(restarted_service.list_events("job-one", workspace_id="workspace-a")), 1)
        with self.assertRaises(JobIdempotencyConflictError):
            restarted_service.submit(changed_spec(make_spec()))


if __name__ == "__main__":
    unittest.main()
