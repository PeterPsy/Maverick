"""Read-only planning and stale-safe, atomic application of bounded imports."""

import json
import sqlite3

from errors import ValidationError
from store import new_id, require_text, row_to_dict, utc_now, write_event
from .import_sources import digest, normalize_source
from .import_writer import write_bundle


def target_fingerprint(db):
    # Include configuration, lifecycle and links, not just counts or timestamps.
    # The catalog comes from SQLite, never from an import-provided identifier.
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
              if not row[0].startswith(("sqlite_", "crm_fts")) and row[0] not in {"import_jobs", "import_rows"}]
    return digest({table: sorted([tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')], key=repr) for table in tables})


def import_plan(db, payload):
    bundle = normalize_source(payload)
    snapshot = sqlite3.connect(":memory:")
    snapshot.row_factory = sqlite3.Row
    try:
        db.backup(snapshot)
        snapshot.execute("PRAGMA foreign_keys=ON")
        target = target_fingerprint(snapshot)
        snapshot.execute("BEGIN")
        try:
            report = write_bundle(snapshot, bundle)
        except (sqlite3.IntegrityError, ValidationError) as error:
            report = {"ok": False, "errors": [{"row": 0, "errors": [str(error)]}], "warnings": bundle["warnings"]}
        report.update(dry_run=True, source_fingerprint=bundle["fingerprint"], target_fingerprint=target,
                      plan_token=digest([bundle["fingerprint"], target]), source_id=bundle["source_id"])
        return report
    finally:
        snapshot.close()


def import_apply(db, payload):
    bundle = normalize_source(payload)
    token = require_text(payload, "plan_token", required=True)
    db.execute("BEGIN IMMEDIATE")
    previous = db.execute("SELECT * FROM import_jobs WHERE plan_token=?", (token,)).fetchone()
    if previous:
        if previous["fingerprint"] != bundle["fingerprint"]:
            raise ValidationError("Plan token belongs to another source.")
        return {**json.loads(previous["report_json"]), "replayed": True}
    expected = digest([bundle["fingerprint"], target_fingerprint(db)])
    if token != expected:
        raise ValidationError("Import plan is stale or source changed. Run a new preview.")
    db.execute("SAVEPOINT import_batch")
    try:
        report = write_bundle(db, bundle)
        if not report["ok"]:
            db.execute("ROLLBACK TO import_batch")
            return {**report, "committed": False, "created_count": 0, "updated_count": 0}
        job_id = new_id("import")
        report.update(committed=True, dry_run=False, job_id=job_id, source_id=bundle["source_id"])
        db.execute("INSERT INTO import_jobs VALUES (?, ?, ?, ?, ?, ?)",
                   (job_id, bundle["source_id"], bundle["fingerprint"], token, json.dumps(report), utc_now()))
        for row in report["rows"]:
            db.execute("INSERT INTO import_rows VALUES (?, ?, ?, ?, ?)",
                       (job_id, row["row"], row["entity_type"], row["entity_id"], row["outcome"]))
        write_event(db, "import.committed", "", "", {"job_id": job_id, "source_fingerprint": bundle["fingerprint"]})
        return report
    finally:
        db.execute("RELEASE import_batch")


def import_jobs(db):
    return {"ok": True, "jobs": [row_to_dict(row) for row in db.execute("SELECT * FROM import_jobs ORDER BY created_at DESC, id LIMIT 50")]}
