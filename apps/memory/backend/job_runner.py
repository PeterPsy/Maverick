"""Execute one leased Memory ingest job."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database import normalize_limit, now_timestamp, transaction
from errors import MemoryValidationError
from ingest_jobs import claim_job, complete_job, fail_job
from lint import lint_memory, mark_wiki_stale
from source_ingestion import ingest_source
from storage_ingestion import ingest_storage_source
from wiki import compile_node


def run_next_job(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    claimed = claim_job(
        data_root,
        {
            "job_types": body.get("job_types"),
            "lease_seconds": body.get("lease_seconds"),
        },
    )
    job = claimed.get("job")
    if not job:
        return {"job": None, "ran": False}

    try:
        result = execute_job(data_root, job)
    except Exception as error:
        failed = fail_job(
            data_root,
            {
                "job_id": job["id"],
                "lease_token": job["lease_token"],
                "error": str(error),
            },
        )
        return {"job": failed["job"], "ran": True, "ok": False, "error": str(error)}

    completed = complete_job(
        data_root,
        {
            "job_id": job["id"],
            "lease_token": job["lease_token"],
        },
    )
    return {"job": completed["job"], "ran": True, "ok": True, "result": result}


def run_jobs_until_idle(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    max_jobs = normalize_limit(body.get("max_jobs"), default=50, minimum=1, maximum=500, field_name="max_jobs")
    stop_on_error = bool(body.get("stop_on_error", True))
    runs: list[dict[str, Any]] = []
    for _index in range(max_jobs):
        run = run_next_job(data_root, body)
        runs.append(run)
        if not run.get("ran"):
            break
        if run.get("ok") is False and stop_on_error:
            break
    executed = [run for run in runs if run.get("ran")]
    failed = [run for run in executed if run.get("ok") is False]
    idle = bool(runs and not runs[-1].get("ran"))
    return {
        "ran": bool(executed),
        "ok": not failed,
        "idle": idle,
        "jobs_run": len(executed),
        "max_jobs": max_jobs,
        "runs": runs,
    }


def execute_job(data_root: Path, job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    job_type = str(job.get("job_type") or "")
    if job_type == "compile_node":
        return compile_node(data_root, payload)
    if job_type == "lint_node":
        return lint_memory(data_root, payload)
    if job_type == "ingest_source":
        if isinstance(payload.get("memory_source"), dict):
            return ingest_storage_source(data_root, {"action": "ingest_storage_source", **payload})
        if payload.get("adapter_id") or isinstance(payload.get("source"), dict):
            return ingest_source(data_root, {"action": "ingest_source", **payload})
        raise MemoryValidationError("ingest_source job payload must include memory_source, adapter_id, or source.")
    if job_type == "mark_stale":
        return mark_stale(data_root, payload)
    if job_type == "requires_storage_reindex":
        return requires_storage_reindex(payload)
    raise MemoryValidationError("unsupported job_type.")


def mark_stale(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    node_id = str(payload.get("node_id") or "").strip()
    if not node_id:
        raise MemoryValidationError("mark_stale job payload requires node_id.")
    reason = str(payload.get("reason") or "job_mark_stale").strip()
    with transaction(data_root, immediate=True) as db:
        stale = mark_wiki_stale(db, node_id, timestamp=now_timestamp(), reason=reason, data_root=data_root)
    return {"node_id": node_id, "compiled_wiki_stale": stale, "reason": reason}


def requires_storage_reindex(payload: dict[str, Any]) -> dict[str, Any]:
    storage_identity = payload.get("storage_identity") if isinstance(payload.get("storage_identity"), dict) else {}
    reindex_suggestion = payload.get("reindex_suggestion") if isinstance(payload.get("reindex_suggestion"), dict) else {}
    impacted_node_ids = payload.get("impacted_node_ids") if isinstance(payload.get("impacted_node_ids"), list) else []
    return {
        "status": "requires_storage_reindex",
        "action_required": True,
        "reason": str(payload.get("reason") or "storage_source_stale"),
        "storage_identity": storage_identity,
        "impacted_node_ids": [str(node_id) for node_id in impacted_node_ids if str(node_id or "").strip()],
        "reindex_suggestion": reindex_suggestion,
    }
