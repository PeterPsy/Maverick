"""Explicit full integrity maintenance and a bounded foreground queue tick."""

from pathlib import Path
from time import monotonic

from database import ensure_schema, record_event, transaction
from job_runner import run_next_job
from source_chunk_index import rebuild_source_chunk_fts, source_chunk_fts_needs_rebuild


def maintain_memory(data_root: Path, body: dict) -> dict:
    ensure_schema(data_root)
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
    return {"repaired": repaired, "jobs_run": len(runs), "runs": runs}
