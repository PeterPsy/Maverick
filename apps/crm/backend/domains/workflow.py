"""Workflow proposal persistence and lifecycle helpers."""

from __future__ import annotations

import json
from typing import Any

from errors import NotFoundError, ValidationError
from store import get_record, new_id, parse_limit, require_text, row_to_dict, utc_now, write_event


WORKFLOW_PROPOSAL_STATUSES = {"pending", "approved", "applied", "dismissed", "rejected"}
ACTIVE_WORKFLOW_PROPOSAL_STATUSES = {"pending", "approved"}
DISMISSAL_WORKFLOW_PROPOSAL_STATUSES = {"dismissed", "rejected"}


def list_workflow_proposals(db, payload: dict[str, Any]) -> list[dict[str, Any]]:
    status = require_text(payload, "status", default="pending") or "pending"
    limit = parse_limit(payload, 50)
    if status in {"active", "open", "reviewable"}:
        placeholders = ", ".join("?" for _ in ACTIVE_WORKFLOW_PROPOSAL_STATUSES)
        rows = db.execute(
            f"SELECT * FROM workflow_proposals WHERE status IN ({placeholders}) ORDER BY updated_at DESC LIMIT ?",
            (*sorted(ACTIVE_WORKFLOW_PROPOSAL_STATUSES), limit),
        ).fetchall()
    elif status == "all":
        rows = db.execute("SELECT * FROM workflow_proposals ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    else:
        _require_workflow_proposal_status(status)
        rows = db.execute("SELECT * FROM workflow_proposals WHERE status = ? ORDER BY updated_at DESC LIMIT ?", (status, limit)).fetchall()
    return [row_to_dict(row) for row in rows]


def approve_workflow_proposal(db, payload: dict[str, Any]) -> dict[str, Any]:
    proposal_id = require_text(payload, "id", required=True)
    proposal = _workflow_proposal(db, proposal_id)
    if proposal["status"] not in {"pending", "approved"}:
        raise ValidationError("Only pending or approved workflow proposals can be approved.", details={"status": proposal["status"]})
    now = utc_now()
    db.execute("UPDATE workflow_proposals SET status = 'approved', approved_at = ?, updated_at = ? WHERE id = ?", (now, now, proposal_id))
    write_event(db, "workflow_proposal.approved", proposal["entity_type"], proposal["entity_id"], {"proposal_id": proposal_id})
    return _workflow_proposal(db, proposal_id)


def dismiss_workflow_proposal(db, payload: dict[str, Any]) -> dict[str, Any]:
    proposal_id = require_text(payload, "id", required=True)
    proposal = _workflow_proposal(db, proposal_id)
    next_status = _dismissal_status(payload)
    if proposal["status"] not in ACTIVE_WORKFLOW_PROPOSAL_STATUSES:
        raise ValidationError(
            "Only pending or approved workflow proposals can be dismissed or rejected.",
            details={"status": proposal["status"], "requested_status": next_status},
        )
    reason = require_text(payload, "reason", default="") or ""
    now = utc_now()
    db.execute("UPDATE workflow_proposals SET status = ?, updated_at = ? WHERE id = ?", (next_status, now, proposal_id))
    event_payload = {"proposal_id": proposal_id, "status": next_status}
    if reason:
        event_payload["reason"] = reason
    write_event(db, f"workflow_proposal.{next_status}", proposal["entity_type"], proposal["entity_id"], event_payload)
    return _workflow_proposal(db, proposal_id)


def _dismissal_status(payload: dict[str, Any]) -> str:
    status = require_text(payload, "status", default="") or require_text(payload, "resolution", default="") or "dismissed"
    if status not in DISMISSAL_WORKFLOW_PROPOSAL_STATUSES:
        raise ValidationError("Workflow proposal dismissal status must be dismissed or rejected.", details={"status": status})
    return status


def _require_workflow_proposal_status(status: str) -> None:
    if status not in WORKFLOW_PROPOSAL_STATUSES:
        raise ValidationError("Workflow proposal status is not supported.", details={"status": status, "allowed": sorted(WORKFLOW_PROPOSAL_STATUSES)})


def _workflow_proposal_duplicate_exists(db, source: str, entity_type: str, entity_id: str, proposal: dict[str, Any]) -> bool:
    action_json = json.dumps(proposal.get("action") if isinstance(proposal.get("action"), dict) else {}, ensure_ascii=True, sort_keys=True)
    rows = db.execute(
        """
        SELECT proposal_json FROM workflow_proposals
        WHERE source = ? AND entity_type = ? AND entity_id = ? AND status IN ('pending', 'approved')
        """,
        (source, entity_type, entity_id),
    ).fetchall()
    for row in rows:
        existing = json.loads(str(row["proposal_json"] or "{}"))
        existing_action = existing.get("action") if isinstance(existing, dict) else {}
        if json.dumps(existing_action if isinstance(existing_action, dict) else {}, ensure_ascii=True, sort_keys=True) == action_json:
            return True
    return False


def _create_workflow_proposal(db, proposal_type: str, entity_type: str, entity_id: str, title: str, proposal: dict[str, Any], *, source: str) -> dict[str, Any]:
    get_record(db, entity_type, entity_id)
    now = utc_now()
    proposal_id = new_id("wf")
    db.execute(
        """
        INSERT INTO workflow_proposals(id, proposal_type, status, entity_type, entity_id, title, proposal_json, source, created_at, updated_at)
        VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
        """,
        (proposal_id, proposal_type, entity_type, entity_id, title, json.dumps(proposal, ensure_ascii=True, sort_keys=True), source, now, now),
    )
    write_event(db, "workflow_proposal.created", entity_type, entity_id, {"proposal_id": proposal_id, "proposal_type": proposal_type})
    return _workflow_proposal(db, proposal_id)


def _workflow_proposal(db, proposal_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM workflow_proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"workflow_proposal `{proposal_id}` was not found.")
    return row_to_dict(row)
