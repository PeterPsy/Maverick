"""Small, strict validators for app-owned records."""
from datetime import UTC, date, datetime
import re
from typing import Any
from uuid import uuid4
from errors import MartaOpsError

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _text(value: object, field: str, *, required: bool = False, max_length: int = 500) -> str:
    if value is not None and not isinstance(value, str):
        raise MartaOpsError(f"{field} deve essere testo.")
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise MartaOpsError(f"{field} è obbligatorio.")
    if len(cleaned) > max_length:
        raise MartaOpsError(f"{field} è troppo lungo.")
    return cleaned


def _choice(value: object, field: str, allowed: set[str], default: str) -> str:
    cleaned = str(value or default).strip()
    if cleaned not in allowed:
        raise MartaOpsError(f"{field} non è valido.")
    return cleaned


def _date(value: object, field: str) -> str:
    cleaned = _text(value, field, max_length=10)
    if not cleaned:
        return ""
    try:
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise MartaOpsError(f"{field} deve essere una data valida.") from exc
    return cleaned


def _email(value: object, field: str) -> str:
    cleaned = _text(value, field, max_length=320)
    if cleaned and not EMAIL_PATTERN.fullmatch(cleaned):
        raise MartaOpsError(f"{field} non è valida.")
    return cleaned


def _money_minor(value: object) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise MartaOpsError("Il valore economico non è valido.")
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise MartaOpsError("Il valore economico non è valido.") from exc
    if amount < 0 or amount > 1_000_000_000:
        raise MartaOpsError("Il valore economico è fuori intervallo.")
    return amount


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise MartaOpsError(f"{field} deve essere vero o falso.")
    return value


def validate_links(state: dict[str, Any], record: dict[str, Any]) -> None:
    for key, collection, label in [("contact_id", "contacts", "Contatto"), ("collaboration_id", "collaborations", "Lavoro")]:
        if record.get(key):
            _find(state[collection], record[key], label)


def _object(body: dict[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise MartaOpsError(f"{key} deve essere un oggetto.")
    return value


def _find(items: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
    for item in items:
        if str(item.get("id") or "") == item_id:
            return item
    raise MartaOpsError(f"{label} non trovato.", status_code=404)
