"""Atomic, anchor-based ordering across complete (possibly filtered) columns."""
from typing import Any
from activity import record_activity
from errors import MartaOpsError
from validation import _choice, _find, _now, _text
from work_records import PHASES

PHASE_LABELS = {"lead": "Contatto", "proposal": "Proposta", "confirmed": "Confermato", "production": "Produzione", "approval": "In approvazione", "scheduled": "Programmato", "published": "Pubblicato", "completed": "Chiuso", "paused": "In pausa", "lost": "Non acquisito"}


def column_items(state: dict[str, Any], phase: str, exclude_id: str = "") -> list[dict[str, Any]]:
    return sorted((item for item in state["collaborations"] if item["phase"] == phase and item["id"] != exclude_id), key=lambda item: item["pipeline_order"])


def next_order(state: dict[str, Any], phase: str) -> int:
    return max((item["pipeline_order"] for item in column_items(state, phase)), default=-1) + 1


def move_work(state: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    item = _find(state["collaborations"], _text(body.get("id"), "Id", required=True, max_length=80), "Lavoro")
    phase = _choice(body.get("phase"), "Fase", PHASES, item["phase"])
    old_phase = item["phase"]
    if body.get("expected_phase") is not None and body["expected_phase"] != old_phase:
        raise MartaOpsError("Il lavoro è stato spostato. Aggiorna la vista e riprova.", status_code=409)
    before_id = _text(body.get("before_id"), "Id destinazione", max_length=80)
    destination = column_items(state, phase, item["id"])
    if before_id:
        anchor = _find(destination, before_id, "Destinazione")
        index = destination.index(anchor)
    else:
        index = len(destination)
    destination.insert(index, item)
    item["phase"] = phase
    item["updated_at"] = _now()
    for index, work in enumerate(destination):
        work["pipeline_order"] = index
    if old_phase != phase:
        for index, work in enumerate(column_items(state, old_phase)):
            work["pipeline_order"] = index
        record_activity(state, f"Fase aggiornata: {item['title']}", text=f"{PHASE_LABELS[old_phase]} → {PHASE_LABELS[phase]}", contact_id=item.get("contact_id", ""), collaboration_id=item["id"])
    return {"collaboration": item}
