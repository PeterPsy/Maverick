"""Explicit integrity maintenance and a platform-scheduled bounded queue tick."""

from pathlib import Path
from time import monotonic
import fcntl

from database import connect, ensure_schema, record_event, transaction
from job_runner import run_next_job
from source_chunk_index import rebuild_source_chunk_fts, source_chunk_fts_needs_rebuild


def maintain_memory(data_root: Path, body: dict) -> dict:
    ensure_schema(data_root)
    # Cross-process exclusion also covers explicit maintenance and recovery.
    # OS releases the lock when a cancelled/crashed hook process exits.
    with (data_root / 'maintenance.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'repaired': False, 'jobs_run': 0, 'runs': [], 'busy': True, 'next_due_in_seconds': 15}
        return _maintain_locked(data_root, body)


def _maintain_locked(data_root: Path, body: dict) -> dict:
    repaired = False
    if body.get("verify_index"):
        with transaction(data_root, immediate=True) as db:
            repaired = source_chunk_fts_needs_rebuild(db, data_root=data_root)
            if repaired:
                rebuild_source_chunk_fts(db, data_root=data_root)
            record_event(db, event_type="memory_index_checked", payload={"repaired": repaired})
    started = monotonic()
    runs = []
    for _ in range(3):
        if monotonic() - started >= 2:
            break
        run = run_next_job(data_root, {"job_types": ["compile_node", "lint_node"], "lease_seconds": 300})
        if not run.get("ran"):
            break
        runs.append({"job_id": run["job"]["id"], "ok": run.get("ok", False)})
        if not run.get("ok"):
            break
    with connect(data_root) as db:
        backlog = db.execute("""SELECT EXISTS(SELECT 1 FROM ingest_jobs
            WHERE job_type IN ('compile_node','lint_node') AND status IN ('ready','running'))""").fetchone()[0]
    return {"repaired": repaired, "jobs_run": len(runs), "runs": runs,
            'next_due_in_seconds': 15 if backlog else 60}
