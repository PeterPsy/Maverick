"""Domain validation and normalized values for candidate operations."""

from __future__ import annotations

from typing import Any
import uuid

DECISIONS = {"da_valutare", "scartato", "riserva", "selezionato"}
EMAIL_STATUSES = {"da_contattare", "email_inviata", "risposta_ricevuta", "nessuna_risposta"}
CALL_STATUSES = {"non_prevista", "da_fissare", "fissata", "fatta", "no_show"}
POC_STATUSES = {"non_previsto", "da_proporre", "proposto", "in_corso", "completato"}
PIPELINE_FIELDS = {"decision", "email_status", "call_status", "poc_status"}
EDITABLE_FIELDS = {
    "name", "email", "city", "bio", "work_status", "has_vat", "profile_code", "profile_label", "profile_answer",
    "traits", "social_usage", "autonomy", "workflow", "platforms", "opportunity", "capacity", "price_proposal",
    "portfolio_url", "portfolio_links", "instagram_links", "test_url", "additional_info", "reviewed", "annotation", "specialty",
    "score_portfolio", "score_budget", "score_test", "form_fit_score", "summary", *PIPELINE_FIELDS,
    "privacy_accepted", "review_rank", "next_action", "next_action_due", "process_notes", "favorite", "archived",
}

ALIASES = {
    "source_response_number": "responseNumber", "source_submitted_at": "submittedAt",
    "work_status": "workStatus", "has_vat": "hasVat", "profile_code": "profileCode",
    "profile_label": "profileShort", "profile_answer": "profile", "social_usage": "socialUsage", "autonomy": "autonomyShort",
    "privacy_accepted": "privacyAccepted", "review_rank": "reviewRank", "price_proposal": "priceProposal",
    "portfolio_url": "portfolioUrl", "portfolio_links": "portfolioLinks", "instagram_links": "instagramLinks",
    "test_url": "testUrl", "additional_info": "additionalInfo",
    "duplicate_submissions": "duplicateSubmissions", "specialty": "area", "score_portfolio": "portfolio",
    "score_budget": "budget", "score_test": "test", "review_score": "reviewScore",
    "form_fit_score": "fitScore", "email_status": "emailStatus", "call_status": "callStatus",
    "poc_status": "pocStatus", "next_action": "nextAction", "next_action_due": "nextActionDue",
    "process_notes": "processNotes",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def value(payload: dict[str, Any], field: str, default: Any = None) -> Any:
    if field in payload:
        return payload[field]
    alias = ALIASES.get(field)
    if alias and alias in payload:
        return payload[alias]
    scores = payload.get("scores")
    if isinstance(scores, dict) and field in {"score_portfolio", "score_budget", "score_test"}:
        return scores.get(field.removeprefix("score_"))
    return default


def text(payload: dict[str, Any], field: str, default: str = "", *, limit: int = 50_000) -> str:
    result = str(value(payload, field, default) or "").strip()
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters.")
    return result


def boolean(payload: dict[str, Any], field: str, default: bool = False) -> bool:
    raw = value(payload, field, default)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "si", "sì"}
    return bool(raw)


def number(payload: dict[str, Any], field: str, default: float | None = None) -> float | None:
    raw = value(payload, field, default)
    if raw in {None, ""}:
        return None
    result = float(raw)
    if result < 0 or result > 10:
        raise ValueError(f"{field} must be between 0 and 10.")
    return round(result, 1)


def string_list(payload: dict[str, Any], field: str) -> list[str]:
    raw = value(payload, field, [])
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(";")]
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be an array.")
    return [str(item).strip()[:500] for item in raw[:50] if str(item).strip()]


def validate_status(field: str, status: str) -> str:
    choices = {
        "decision": DECISIONS,
        "email_status": EMAIL_STATUSES,
        "call_status": CALL_STATUSES,
        "poc_status": POC_STATUSES,
    }[field]
    if status not in choices:
        raise ValueError(f"Unsupported {field}: {status}")
    return status
