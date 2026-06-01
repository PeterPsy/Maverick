"""Website intake workflow for CRM-owned lead capture and notifications."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

from errors import ValidationError
from store import get_record, new_id, require_text, row_to_dict, utc_now, write_event

from .external_refs import link_external_ref
from .lead_records import create_lead


MailSender = Callable[[str, dict[str, Any]], dict[str, Any]]

SOURCE_LABELS = {
    "vform": "Video form",
    "overlay": "Overlay CTA",
    "onboarding": "Onboarding backup",
}
CONTACT_LABELS = {"email": "Email", "call": "Telefonata", "video-call": "Video call"}
CONTACT_NEXT_STEPS = {
    "email": "Ti rispondiamo via email con le prime domande utili e una proposta di passo successivo.",
    "call": "Ti chiamiamo per allinearci sul contesto e capire dove conviene intervenire prima.",
    "video-call": "Ti proponiamo il primo confronto in video call, con un'agenda chiara e niente giri a vuoto.",
}
REQUEST_LABELS = {
    "audit": "Audit e mappatura",
    "demo": "Demo guidata",
    "project": "Soluzione su misura",
    "training": "Formazione e adozione",
    "other": "Richiesta da qualificare",
}
SERVICE_LABELS = {
    "ai-audit": "AI audit e operations",
    "custom-development": "Sviluppo e automazione custom",
    "social-automation": "Social Automation",
    "maverick": "Maverick",
    "training": "Training e adozione",
    "other": "Area da definire insieme",
}
SOURCE_PROFILES = {
    "vform": (
        "Video form ricevuto",
        "Abbiamo ricevuto il tuo video form. Ci hai gia dato il contesto che evita una prima call piena di domande doppie.",
    ),
    "overlay": (
        "Richiesta ricevuta",
        "Abbiamo ricevuto il form rapido. Pochi campi, quanto basta per capire da dove partire senza chiederti un romanzo.",
    ),
    "onboarding": (
        "Onboarding ricevuto",
        "Abbiamo ricevuto il form completo. C'e abbastanza contesto per iniziare a ragionare sul prossimo passo con criterio.",
    ),
}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
WEBSITE_LEAD_OWNER_ID = "Peter.fioretti94@gmail.com"


def ingest_website_intake(db, payload: dict[str, Any]) -> dict[str, Any]:
    submission_id = require_text(payload, "submission_id", required=True)
    existing = db.execute("SELECT * FROM website_intakes WHERE submission_id = ?", (submission_id,)).fetchone()
    retry_failed = bool(payload.get("retry_failed_email"))
    if existing is None:
        lead = _create_lead_from_submission(db, payload)
        intake = _insert_intake(db, payload, lead)
        link_external_ref(db, _website_external_ref_payload(intake, lead, payload))
        write_event(db, "website_intake.accepted", "lead", lead["id"], {"submission_id": submission_id})
        db.commit()
    else:
        intake = row_to_dict(existing)
        lead = get_record(db, "lead", str(intake["lead_id"]))
        if str(intake.get("email_status") or "") == "sent" or not retry_failed:
            return _response(db, intake, lead, status_code="duplicate")

    if not _should_send_notifications(payload):
        _update_intake_email_status(db, str(intake["id"]), "skipped")
        db.commit()
        intake = _intake_by_id(db, str(intake["id"]))
        return _response(db, intake, lead, status_code="accepted")

    messages = _notification_messages(payload)
    if not messages:
        _update_intake_email_status(db, str(intake["id"]), "skipped")
        db.commit()
        intake = _intake_by_id(db, str(intake["id"]))
        return _response(db, intake, lead, status_code="accepted")

    try:
        provider_app_id = _selected_provider_app_id(payload, "mail")
    except ValidationError as error:
        outcomes = []
        for message in messages:
            outbox = _ensure_outbox_item(db, str(intake["id"]), str(lead["id"]), message, "")
            outcomes.append(_fail_outbox_item(db, outbox, str(error), increment_attempts=False))
        _update_intake_email_status(db, str(intake["id"]), _combined_email_status(outcomes))
        write_event(
            db,
            "website_intake.email_failed",
            "lead",
            str(lead["id"]),
            {"submission_id": submission_id, "reason": "mail_provider_unavailable"},
        )
        db.commit()
        intake = _intake_by_id(db, str(intake["id"]))
        return _response(db, intake, lead, status_code="accepted", outbox=outcomes)

    sender = payload.get("_mail_sender")
    if sender is not None and not callable(sender):
        raise ValidationError("`_mail_sender` must be callable when provided.")
    maverick_command = _maverick_command(payload)
    mail_sender: MailSender = (
        sender
        if callable(sender)
        else lambda provider, mail_payload: _send_mail_with_maverick(
            provider,
            mail_payload,
            maverick_command=maverick_command,
        )
    )

    outcomes: list[dict[str, Any]] = []
    for message in messages:
        outbox = _ensure_outbox_item(db, str(intake["id"]), str(lead["id"]), message, provider_app_id)
        if outbox["status"] == "sent":
            outcomes.append(outbox)
            continue
        db.commit()
        outcome = _send_outbox_item(db, outbox, provider_app_id, mail_sender)
        outcomes.append(outcome)
        if outcome["status"] == "sent":
            _link_mail_result(db, lead, message, provider_app_id, outcome)
        db.commit()

    email_status = _combined_email_status(outcomes)
    _update_intake_email_status(db, str(intake["id"]), email_status)
    write_event(db, f"website_intake.email_{email_status}", "lead", str(lead["id"]), {"submission_id": submission_id})
    db.commit()
    intake = _intake_by_id(db, str(intake["id"]))
    return _response(db, intake, lead, status_code="accepted", outbox=outcomes)


def _create_lead_from_submission(db, payload: dict[str, Any]) -> dict[str, Any]:
    contact = _object(payload.get("contact"), "contact")
    request = _object(payload.get("request"), "request")
    email = _text(contact.get("email")).lower()
    if not EMAIL_RE.match(email):
        raise ValidationError("`contact.email` must be a valid email address.")
    name = _text(contact.get("name")) or email
    first_name, last_name = _split_name(name)
    website = _text(contact.get("website"))
    domain = _domain_from_url(website)
    summary = _lead_summary(request, payload.get("answers"))
    return create_lead(
        db,
        {
            "first_name": first_name,
            "last_name": last_name,
            "display_name": name,
            "email": email,
            "phone": _text(contact.get("phone")),
            "company": _text(contact.get("company")),
            "domain": domain,
            "source": f"website:{_text(payload.get('source')) or 'unknown'}",
            "status": "new",
            "owner_id": WEBSITE_LEAD_OWNER_ID,
            "summary": summary,
            "metadata": {
                "website_intake": _public_payload(payload),
                "submission_id": require_text(payload, "submission_id", required=True),
            },
        },
    )


def _insert_intake(db, payload: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    intake_id = new_id("intake")
    contact = _object(payload.get("contact"), "contact")
    db.execute(
        """
        INSERT INTO website_intakes(
          id, submission_id, lead_id, source, contact_email, status, email_status,
          payload_json, server_meta_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'accepted', 'pending', ?, ?, ?, ?)
        """,
        (
            intake_id,
            require_text(payload, "submission_id", required=True),
            lead["id"],
            _text(payload.get("source")) or "website",
            _text(contact.get("email")).lower(),
            json.dumps(_public_payload(payload), ensure_ascii=True, sort_keys=True),
            json.dumps(_object(payload.get("server_meta"), "server_meta", required=False), ensure_ascii=True, sort_keys=True),
            now,
            now,
        ),
    )
    return _intake_by_id(db, intake_id)


def _ensure_outbox_item(db, intake_id: str, lead_id: str, message: dict[str, Any], provider_app_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM crm_outbox WHERE intake_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1",
        (intake_id, message["kind"]),
    ).fetchone()
    now = utc_now()
    request_json = json.dumps(message["mail_payload"], ensure_ascii=True, sort_keys=True)
    if row is None:
        outbox_id = new_id("outbox")
        db.execute(
            """
            INSERT INTO crm_outbox(
              id, intake_id, entity_type, entity_id, kind, provider_alias, provider_app_id,
              status, attempts, request_json, result_json, last_error, created_at, updated_at, processed_at
            )
            VALUES (?, ?, 'lead', ?, ?, 'mail', ?, 'pending', 0, ?, '{}', '', ?, ?, '')
            """,
            (outbox_id, intake_id, lead_id, message["kind"], provider_app_id, request_json, now, now),
        )
        return _outbox_by_id(db, outbox_id)
    db.execute(
        """
        UPDATE crm_outbox
        SET provider_app_id = ?, request_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (provider_app_id, request_json, now, row["id"]),
    )
    return _outbox_by_id(db, str(row["id"]))


def _send_outbox_item(db, outbox: dict[str, Any], provider_app_id: str, mail_sender: MailSender) -> dict[str, Any]:
    request_value = outbox.get("request") or {}
    request_payload = request_value if isinstance(request_value, dict) else json.loads(str(request_value or "{}"))
    now = utc_now()
    attempts = int(outbox.get("attempts") or 0) + 1
    db.execute(
        "UPDATE crm_outbox SET status = 'sending', attempts = ?, updated_at = ? WHERE id = ?",
        (attempts, now, outbox["id"]),
    )
    try:
        result = mail_sender(provider_app_id, request_payload)
    except Exception as error:  # noqa: BLE001 - persisted as outbox failure detail.
        message = str(error)[:500]
        db.execute(
            """
            UPDATE crm_outbox
            SET status = 'failed', attempts = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (attempts, message, utc_now(), outbox["id"]),
        )
        return _outbox_by_id(db, str(outbox["id"]))
    db.execute(
        """
        UPDATE crm_outbox
        SET status = 'sent', attempts = ?, result_json = ?, last_error = '', processed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (attempts, json.dumps(result, ensure_ascii=True, sort_keys=True), utc_now(), utc_now(), outbox["id"]),
    )
    return _outbox_by_id(db, str(outbox["id"]))


def _fail_outbox_item(db, outbox: dict[str, Any], message: str, *, increment_attempts: bool = True) -> dict[str, Any]:
    attempts = int(outbox.get("attempts") or 0) + (1 if increment_attempts else 0)
    db.execute(
        """
        UPDATE crm_outbox
        SET status = 'failed', attempts = ?, last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (attempts, message[:500], utc_now(), outbox["id"]),
    )
    return _outbox_by_id(db, str(outbox["id"]))


def _send_mail_with_maverick(provider_app_id: str, payload: dict[str, Any], *, maverick_command: str | None = None) -> dict[str, Any]:
    args = [
        maverick_command or _maverick_command({}),
        "app",
        provider_app_id,
        "mcp",
        "call",
        "mail_send",
        "--json",
    ]
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            args.extend([flag, "true" if value else "false"])
        elif isinstance(value, (list, dict)):
            args.extend([flag, json.dumps(value, ensure_ascii=True)])
        else:
            args.extend([flag, str(value)])
    completed = subprocess.run(args, text=True, capture_output=True, timeout=45, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "mail_send failed").strip())
    result = json.loads(completed.stdout or "{}")
    status_code = int(result.get("status_code") or 200)
    if status_code >= 400 or result.get("error"):
        raise RuntimeError(str(result.get("detail") or result.get("message") or result.get("error") or "mail_send failed"))
    return result


def _maverick_command(payload: dict[str, Any]) -> str:
    explicit = _text(payload.get("_maverick_command") or payload.get("maverick_command"))
    if explicit:
        return explicit
    configured = _text(os.environ.get("MAVERICK_COMMAND"))
    if configured:
        return configured
    found = shutil.which("maverick")
    if found:
        return found
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "maverick"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "maverick"


def _link_mail_result(db, lead: dict[str, Any], message: dict[str, Any], provider_app_id: str, outbox: dict[str, Any]) -> None:
    result = _object(outbox.get("result"), "result", required=False)
    draft = _object(result.get("draft"), "draft", required=False)
    send_result = _object(result.get("result"), "result.result", required=False)
    thread_id = _text(send_result.get("thread_id"))
    draft_id = _text(draft.get("id"))
    provider_message_id = _text(send_result.get("provider_message_id"))
    source_entity_type = "email_thread" if thread_id else "mail_draft"
    source_entity_id = thread_id or draft_id or str(outbox["id"])
    link_external_ref(
        db,
        {
            "crm_entity_type": "lead",
            "crm_entity_id": lead["id"],
            "source_app_id": provider_app_id,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
            "link_type": "email",
            "title": message["title"],
            "summary": message["summary"],
            "metadata": {
                "provider_alias": "mail",
                "source_interface": "mail.workspace",
                "message_kind": message["kind"],
                "outbox_id": outbox["id"],
                "draft_id": draft_id,
                "provider_message_id": provider_message_id,
            },
        },
    )


def _notification_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    contact = _object(payload.get("contact"), "contact")
    notification = _object(payload.get("notification"), "notification", required=False)
    team_email = _text(notification.get("team_email") or payload.get("team_email"))
    send_team = bool(notification.get("send_team", True))
    send_lead = bool(notification.get("send_lead", True))
    messages: list[dict[str, Any]] = []
    if send_team and team_email:
        team = _build_team_email(payload, team_email)
        messages.append(
            {
                "kind": "website_intake_team_notification",
                "title": "Website intake team notification",
                "summary": f"Internal notification for {require_text(payload, 'submission_id', required=True)}",
                "mail_payload": {
                    "to": [{"email": team_email}],
                    "reply_to": [{"email": _text(contact.get("email")), "name": _text(contact.get("name"))}],
                    "subject": team["subject"],
                    "body_text": team["text"],
                    "confirm": True,
                },
            }
        )
    if send_lead:
        lead = _build_lead_email(payload, team_email or "team@loopino.ai")
        messages.append(
            {
                "kind": "website_intake_lead_confirmation",
                "title": "Website intake lead confirmation",
                "summary": f"Lead confirmation for {require_text(payload, 'submission_id', required=True)}",
                "mail_payload": {
                    "to": [{"email": _text(contact.get("email")), "name": _text(contact.get("name"))}],
                    "reply_to": [{"email": team_email or "team@loopino.ai", "name": "Loopino"}],
                    "subject": lead["subject"],
                    "body_text": lead["text"],
                    "body_html": lead["html"],
                    "confirm": True,
                },
            }
        )
    return messages


def _build_team_email(payload: dict[str, Any], recipient_email: str) -> dict[str, str]:
    contact = _object(payload.get("contact"), "contact")
    request = _object(payload.get("request"), "request")
    source_context = _object(payload.get("source_context"), "source_context", required=False)
    source_label = SOURCE_LABELS.get(_text(payload.get("source")), _text(payload.get("source")) or "website")
    contact_method = CONTACT_LABELS.get(_text(request.get("preferred_contact")), _text(request.get("preferred_contact")))
    subject = f"[Loopino intake] {source_label} - {contact_method} - {_text(contact.get('email'))}"
    answers = _flatten_answers(payload.get("answers"))
    text = "\n".join(
        [
            "Nuova richiesta dal sito Loopino",
            "",
            _pair("Submission ID", require_text(payload, "submission_id", required=True)),
            _pair("Ricevuta", _text(payload.get("received_at"))),
            _pair("Fonte form", source_label),
            _pair("Pagina", _text(source_context.get("page_source"))),
            _pair("Percorso", _text(source_context.get("source_path"))),
            _pair("CTA/entry", _text(source_context.get("entry_label"))),
            "",
            "Contatto",
            _pair("Nome", _text(contact.get("name"))),
            _pair("Email", _text(contact.get("email"))),
            _pair("Telefono", _text(contact.get("phone"))),
            _pair("Azienda", _text(contact.get("company"))),
            _pair("Sito", _text(contact.get("website"))),
            "",
            "Richiesta",
            _pair("Tipo", _text(request.get("type"))),
            _pair("Servizio", _text(request.get("service_interest"))),
            _pair("Obiettivo", _text(request.get("primary_goal"))),
            _pair("Ricontatto", contact_method),
            _pair("Urgenza", _text(request.get("urgency"))),
            _pair("Team", _text(request.get("team_size"))),
            "",
            "Risposte e note",
            answers or "-",
            "",
            f"Destinatario operativo: {recipient_email}",
        ]
    )
    return {"subject": subject, "text": text}


def _build_lead_email(payload: dict[str, Any], team_email: str) -> dict[str, str]:
    contact = _object(payload.get("contact"), "contact")
    request = _object(payload.get("request"), "request")
    first_name = _text(contact.get("name")).split(" ")[0].strip()
    greeting = f"Ciao {first_name}" if first_name else "Ciao"
    eyebrow, intro = SOURCE_PROFILES.get(_text(payload.get("source")), SOURCE_PROFILES["onboarding"])
    service_label = SERVICE_LABELS.get(_text(request.get("service_interest")), _text(request.get("service_interest")) or "-")
    contact_method = CONTACT_LABELS.get(_text(request.get("preferred_contact")), _text(request.get("preferred_contact")) or "-")
    next_step = CONTACT_NEXT_STEPS.get(
        _text(request.get("preferred_contact")),
        "Ti ricontattiamo con il prossimo passo utile, senza trasformare tutto in un labirinto di email.",
    )
    rows = _lead_summary_rows(payload)
    subject = "Richiesta ricevuta | Loopino"
    text = "\n".join(
        [
            f"{greeting},",
            "",
            intro,
            "",
            f"Area indicata: {service_label}.",
            f"Canale scelto: {contact_method}.",
            "",
            "Cosa succede ora:",
            "1. Leggiamo il contesto che hai condiviso.",
            "2. Isoliamo il primo punto utile su cui lavorare.",
            f"3. {next_step}",
            "",
            "Riepilogo:",
            *[f"- {label}: {value}" for label, value in rows],
            "",
            f"Se vuoi aggiungere un dettaglio, rispondi a questa email o scrivici a {team_email}.",
            "Niente newsletter infinita: questa e solo la conferma della richiesta. Ora entra in scena una persona.",
            "",
            "Loopino",
        ]
    )
    rows_html = "".join(
        f"<tr><td style=\"padding:12px 0;border-bottom:1px solid #343530;color:#a4a5a1;font-size:12px;line-height:1.4;text-transform:uppercase;letter-spacing:.12em;font-family:Arial,sans-serif;\">{html.escape(label)}</td>"
        f"<td style=\"padding:12px 0 12px 16px;border-bottom:1px solid #343530;color:#f9faf9;font-size:14px;line-height:1.45;font-family:Arial,sans-serif;text-align:right;\">{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    reply_subject = f"Dettaglio richiesta {require_text(payload, 'submission_id', required=True)}"
    mailto_href = f"mailto:{team_email}?subject={quote(reply_subject)}"
    body_html = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>{html.escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#0b0b0a;color:#f9faf9;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">Abbiamo ricevuto la tua richiesta: ora la leggiamo, la mettiamo in ordine e ti rispondiamo con il prossimo passo.</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b0b0a;border-collapse:collapse;"><tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;border-collapse:collapse;">
<tr><td style="padding:0 0 18px 0;"><div style="font-family:Arial,sans-serif;font-size:20px;line-height:1;font-weight:800;letter-spacing:.18em;color:#c8cfc0;">LOOPINO<span style="color:#a0e84f;">.</span></div></td></tr>
<tr><td style="background:#1a1b18;border:1px solid #343530;border-radius:8px;padding:34px 30px 30px 30px;box-shadow:0 24px 56px rgba(0,0,0,.34);">
<p style="margin:0 0 16px 0;color:#a0e84f;font-family:Arial,sans-serif;font-size:12px;line-height:1.3;text-transform:uppercase;letter-spacing:.18em;font-weight:700;">{html.escape(eyebrow)}</p>
<h1 style="margin:0 0 18px 0;color:#c8cfc0;font-family:Arial,sans-serif;font-size:32px;line-height:1.08;letter-spacing:-.02em;font-weight:800;">{html.escape(greeting)}, abbiamo preso il segnale.</h1>
<p style="margin:0;color:#f9faf9;font-family:Arial,sans-serif;font-size:16px;line-height:1.65;">{html.escape(intro)}</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:26px 0;border-collapse:collapse;background:#262624;border:1px solid #41423e;border-radius:8px;"><tr><td style="padding:18px 20px;">
<p style="margin:0 0 12px 0;color:#a4a5a1;font-family:Arial,sans-serif;font-size:12px;line-height:1.3;text-transform:uppercase;letter-spacing:.14em;">Riepilogo rapido</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">{rows_html}</table>
</td></tr></table>
<h2 style="margin:0 0 12px 0;color:#c8cfc0;font-family:Arial,sans-serif;font-size:20px;line-height:1.2;font-weight:800;">Cosa succede ora</h2>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
<tr><td style="width:28px;padding:5px 0 10px 0;vertical-align:top;color:#0b0b0a;"><span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:#a0e84f;color:#0b0b0a;font-family:Arial,sans-serif;font-size:12px;line-height:22px;text-align:center;font-weight:800;">1</span></td><td style="padding:3px 0 10px 0;color:#f9faf9;font-family:Arial,sans-serif;font-size:15px;line-height:1.55;">Leggiamo il contesto che hai condiviso.</td></tr>
<tr><td style="width:28px;padding:5px 0 10px 0;vertical-align:top;color:#0b0b0a;"><span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:#a0e84f;color:#0b0b0a;font-family:Arial,sans-serif;font-size:12px;line-height:22px;text-align:center;font-weight:800;">2</span></td><td style="padding:3px 0 10px 0;color:#f9faf9;font-family:Arial,sans-serif;font-size:15px;line-height:1.55;">Isoliamo il primo punto utile su cui lavorare.</td></tr>
<tr><td style="width:28px;padding:5px 0 0 0;vertical-align:top;color:#0b0b0a;"><span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:#a0e84f;color:#0b0b0a;font-family:Arial,sans-serif;font-size:12px;line-height:22px;text-align:center;font-weight:800;">3</span></td><td style="padding:3px 0 0 0;color:#f9faf9;font-family:Arial,sans-serif;font-size:15px;line-height:1.55;">{html.escape(next_step)}</td></tr>
</table>
<p style="margin:24px 0 0 0;padding:16px 18px;background:#0f100e;border-left:3px solid #a0e84f;color:#d4d5d2;font-family:Arial,sans-serif;font-size:14px;line-height:1.6;">Niente newsletter infinita: questa e solo la conferma della richiesta. Ora entra in scena una persona.</p>
<table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:26px;border-collapse:collapse;"><tr><td style="background:#a0e84f;border-radius:6px;"><a href="{html.escape(mailto_href)}" style="display:inline-block;padding:13px 18px;color:#0b0b0a;font-family:Arial,sans-serif;font-size:14px;line-height:1;font-weight:800;text-decoration:none;">Aggiungi un dettaglio</a></td></tr></table>
</td></tr>
<tr><td style="padding:18px 4px 0 4px;color:#a4a5a1;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;">Questa email conferma una richiesta inviata dal sito Loopino. Puoi rispondere direttamente o scrivere a <a href="mailto:{html.escape(team_email)}" style="color:#c8cfc0;text-decoration:underline;">{html.escape(team_email)}</a>.</td></tr>
</table></td></tr></table>
</body></html>"""
    return {"subject": subject, "text": text, "html": body_html}


def _selected_provider_app_id(payload: dict[str, Any], alias: str) -> str:
    explicit = _text(payload.get(f"{alias}_provider_app_id") or payload.get("provider_app_id"))
    if explicit:
        return explicit
    dependencies = payload.get("_app_dependencies") or payload.get("app_dependencies") or {}
    provider = _provider_from_dependencies(dependencies, alias)
    if provider:
        return provider
    try:
        completed = subprocess.run(
            [_maverick_command(payload), "core", "cli", "run", "app.crm.dependencies", "--json"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if completed.returncode == 0:
            provider = _provider_from_dependencies(json.loads(completed.stdout or "{}"), alias)
            if provider:
                return provider
    except Exception:
        pass
    raise ValidationError(f"CRM dependency alias `{alias}` has no selected provider app.")


def _provider_from_dependencies(dependencies: object, alias: str) -> str:
    items = dependencies.get("dependencies") if isinstance(dependencies, dict) else None
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict) or item.get("alias") != alias:
            continue
        provider_ids = item.get("selected_provider_app_ids")
        if isinstance(provider_ids, list) and provider_ids:
            return _text(provider_ids[0])
    return ""


def _response(db, intake: dict[str, Any], lead: dict[str, Any], *, status_code: str, outbox: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    outbox_items = outbox if outbox is not None else [_outbox_from_row(row) for row in db.execute("SELECT * FROM crm_outbox WHERE intake_id = ? ORDER BY created_at", (intake["id"],)).fetchall()]
    return {
        "ok": True,
        "status": status_code,
        "submission_id": intake["submission_id"],
        "intake": intake,
        "lead": lead,
        "email_status": intake.get("email_status", ""),
        "outbox": outbox_items,
    }


def _combined_email_status(outcomes: list[dict[str, Any]]) -> str:
    if not outcomes:
        return "skipped"
    statuses = {str(item.get("status") or "") for item in outcomes}
    if statuses == {"sent"}:
        return "sent"
    if "sent" in statuses:
        return "partial_failed"
    return "failed"


def _update_intake_email_status(db, intake_id: str, status: str) -> None:
    db.execute("UPDATE website_intakes SET email_status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), intake_id))


def _intake_by_id(db, intake_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM website_intakes WHERE id = ?", (intake_id,)).fetchone()
    if row is None:
        raise ValidationError("Website intake was not found.")
    return row_to_dict(row)


def _outbox_by_id(db, outbox_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM crm_outbox WHERE id = ?", (outbox_id,)).fetchone()
    if row is None:
        raise ValidationError("CRM outbox item was not found.")
    return _outbox_from_row(row)


def _outbox_from_row(row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["request"] = item.pop("request", {})
    item["result"] = item.pop("result", {})
    return item


def _website_external_ref_payload(intake: dict[str, Any], lead: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "crm_entity_type": "lead",
        "crm_entity_id": lead["id"],
        "source_app_id": "loopino-website",
        "source_entity_type": "website_intake",
        "source_entity_id": intake["submission_id"],
        "link_type": "website_intake",
        "title": f"Website intake {intake['submission_id']}",
        "summary": _lead_summary(_object(payload.get("request"), "request"), payload.get("answers")),
        "occurred_at": _text(payload.get("received_at")),
        "metadata": {"provider_alias": "agent", "source_interface": "website.form", "intake_id": intake["id"]},
    }


def _should_send_notifications(payload: dict[str, Any]) -> bool:
    notification = _object(payload.get("notification"), "notification", required=False)
    return bool(notification.get("enabled", payload.get("send_notifications", True)))


def _lead_summary(request: dict[str, Any], answers: object) -> str:
    parts = [
        SERVICE_LABELS.get(_text(request.get("service_interest")), _text(request.get("service_interest"))),
        REQUEST_LABELS.get(_text(request.get("type")), _text(request.get("type"))),
        _text(request.get("primary_goal")),
        _text(_object(answers, "answers", required=False).get("challenge_summary")),
    ]
    return " | ".join(part for part in parts if part)[:1000]


def _lead_summary_rows(payload: dict[str, Any]) -> list[tuple[str, str]]:
    request = _object(payload.get("request"), "request")
    rows = [
        ("Area", SERVICE_LABELS.get(_text(request.get("service_interest")), _text(request.get("service_interest")) or "-")),
        ("Tipo richiesta", REQUEST_LABELS.get(_text(request.get("type")), _text(request.get("type")) or "-")),
        ("Canale scelto", CONTACT_LABELS.get(_text(request.get("preferred_contact")), _text(request.get("preferred_contact")) or "-")),
    ]
    slot = _text(_object(payload.get("answers"), "answers", required=False).get("ricontatto_slot"))
    if slot:
        rows.append(("Slot indicato", slot))
    rows.append(("Riferimento", require_text(payload, "submission_id", required=True)))
    return rows


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _object(value: object, field: str, *, required: bool = True) -> dict[str, Any]:
    if value in (None, "") and not required:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"`{field}` must be an object.")
    return value


def _text(value: object) -> str:
    return str(value or "").strip()


def _pair(label: str, value: str) -> str:
    return f"{label}: {value or '-'}"


def _flatten_answers(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    rows: list[str] = []
    for key, answer in value.items():
        if isinstance(answer, list):
            rendered = ", ".join(_text(item) for item in answer if _text(item))
        elif isinstance(answer, dict):
            rendered = json.dumps(answer, ensure_ascii=True, sort_keys=True)
        else:
            rendered = _text(answer)
        rows.append(_pair(str(key), rendered))
    return "\n".join(rows)


def _split_name(name: str) -> tuple[str, str]:
    parts = [part for part in name.split() if part]
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _domain_from_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.netloc or parsed.path).removeprefix("www.").lower()
