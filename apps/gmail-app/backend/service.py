"""Gmail App service layer shared by backend, CLI, and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import GmailAppValidationError
from gmail_client import client_from_body
from gmail_models import email_domain
from oauth_service import authorization_url, exchange_code, refresh_access_token
from store import (
    consume_send_approval,
    create_send_approval,
    create_suggestion,
    get_message,
    get_thread,
    health_payload,
    list_accounts,
    list_audit,
    list_suggestions,
    list_threads,
    mark_thread_read,
    mark_suggestion_decision,
    reference_search_messages,
    reference_search_threads,
    record_audit,
    record_sent_message,
    save_thread,
    upsert_account,
)

REFERENCE_MANIFEST = {
    "app_id": "gmail-app",
    "schema_version": "1",
    "entity_types": [
        {
            "entity_type": "thread",
            "display_name": "Gmail Thread",
            "id_stability": "stable",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        },
        {
            "entity_type": "message",
            "display_name": "Gmail Message",
            "id_stability": "stable",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        },
    ],
}


def action_from_tool(tool_name: str, fallback: str) -> str:
    mapping = {
        "gmail_app_connection_status": "connection.status",
        "gmail_app_oauth_authorization_url": "oauth.authorization_url",
        "gmail_app_oauth_exchange": "oauth.exchange",
        "gmail_app_search_threads": "threads.search",
        "gmail_app_latest_threads": "threads.latest",
        "gmail_app_get_thread": "threads.get",
        "gmail_app_summarize_thread": "threads.summarize",
        "gmail_app_prepare_reply": "compose.prepare_reply",
        "gmail_app_request_send_approval": "send.request_approval",
        "gmail_app_send_approved": "send.approved",
        "gmail_app_list_relationship_suggestions": "suggestions.list",
        "gmail_app_mark_relationship_suggestion": "suggestions.mark_reviewed",
        "gmail_app_audit_recent": "audit.recent",
        "gmail_app_reference_manifest": "references.manifest",
        "gmail_app_reference_search": "references.search",
        "gmail_app_reference_resolve": "references.resolve",
        "gmail_app_reference_summarize": "references.summarize",
    }
    return mapping.get(tool_name, fallback)


def handle_action(data_root: Path, body: dict[str, Any], *, workspace_id: str = "default", app_secrets: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    app_secrets = app_secrets or {}
    action = str(body.get("action") or "connection.status").strip()
    if action == "connection.status":
        accounts = [
            {**account, "has_oauth_secret_ref": bool(app_secrets.get("gmail-oauth"))}
            for account in list_accounts(data_root)
        ]
        return 200, {"connected_accounts": accounts, "health": health_payload(data_root)}
    if action == "connection.configure":
        account = upsert_account(
            data_root,
            str(body.get("email") or "").strip().lower(),
            display_name=str(body.get("display_name") or ""),
            oauth_secret_ref=str(body.get("oauth_secret_ref") or ""),
        )
        return 200, {"account": account}
    if action == "oauth.authorization_url":
        return 200, authorization_url(body)
    if action == "oauth.exchange":
        result = exchange_code(body)
        token_secret = result.pop("token_secret", {})
        account = result.get("account") if isinstance(result.get("account"), dict) else {}
        email = str(account.get("email") or "").strip().lower()
        if email:
            upsert_account(data_root, email, display_name=email)
            record_audit(data_root, "gmail.oauth_connected", subject_id=email, payload={"has_refresh_token": result["token"]["has_refresh_token"]})
        if isinstance(token_secret, dict) and (token_secret.get("refresh_token") or token_secret.get("access_token")):
            result["_platform_secret_writes"] = [
                {
                    "logical_name": "gmail-oauth",
                    "alias": "default-gmail-app-oauth",
                    "label": "Gmail App OAuth token",
                    "description": "Google OAuth refresh credentials for Gmail App.",
                    "raw_value": token_secret,
                }
            ]
        return 200, result
    if action == "threads.search":
        body = with_secret_access_token(body, app_secrets)
        client = client_from_body(body)
        query = str(body.get("query") or "").strip()
        limit = int(body.get("limit") or 10)
        threads = [save_thread(data_root, thread) for thread in client.search_threads(query, limit=limit)]
        record_audit(data_root, "gmail.threads_searched", subject_id=query, payload={"query": query, "count": len(threads)})
        return 200, {"threads": threads}
    if action == "threads.latest":
        limit = int(body.get("limit") or 100)
        cached_threads = list_threads(data_root, "", limit)
        if cached_threads and not body.get("force_refresh"):
            record_audit(data_root, "gmail.latest_threads_cache_used", payload={"count": len(cached_threads), "limit": limit})
            return 200, {"threads": cached_threads, "source": "cache"}
        body = with_secret_access_token(body, app_secrets)
        client = client_from_body(body)
        threads = [save_thread(data_root, thread) for thread in client.search_threads("", limit=limit)]
        record_audit(data_root, "gmail.latest_threads_loaded", payload={"count": len(threads), "limit": limit})
        return 200, {"threads": threads, "source": "gmail"}
    if action == "threads.spam":
        limit = int(body.get("limit") or 100)
        cached_threads = list_threads(data_root, "", limit, include_system_labels=True, required_label="SPAM")
        if cached_threads and not body.get("force_refresh"):
            record_audit(data_root, "gmail.spam_threads_cache_used", payload={"count": len(cached_threads), "limit": limit})
            return 200, {"threads": cached_threads, "source": "cache"}
        body = with_secret_access_token(body, app_secrets)
        client = client_from_body(body)
        threads = [save_thread(data_root, thread) for thread in client.search_threads("in:spam", limit=limit, include_spam_trash=True)]
        spam_threads = [thread for thread in threads if "SPAM" in {str(label).upper() for label in thread.get("labels", [])}]
        record_audit(data_root, "gmail.spam_threads_loaded", payload={"count": len(spam_threads), "limit": limit})
        return 200, {"threads": spam_threads, "source": "gmail"}
    if action == "threads.page":
        limit = int(body.get("limit") or 50)
        offset = int(body.get("offset") or 0)
        page_token = str(body.get("page_token") or "")
        query = str(body.get("query") or "").strip()
        include_system_labels = bool(body.get("include_system_labels"))
        required_label = str(body.get("required_label") or "")
        excluded_labels = [str(label) for label in body.get("excluded_labels", []) if str(label)]
        force_remote = bool(body.get("force_remote")) or bool(page_token)
        if not force_remote:
            cached_threads = list_threads(
                data_root,
                "",
                limit + 1,
                include_system_labels=include_system_labels,
                required_label=required_label,
                excluded_labels=excluded_labels,
                offset=offset,
            )
            if cached_threads:
                has_more = len(cached_threads) > max(1, min(limit, 100))
                cached_page = cached_threads[: max(1, min(limit, 100))]
                record_audit(
                    data_root,
                    "gmail.thread_page_cache_used",
                    payload={"count": len(cached_page), "limit": limit, "offset": offset, "required_label": required_label, "excluded_labels": excluded_labels, "has_more": has_more},
                )
                return 200, {"threads": cached_page, "source": "cache", "next_page_token": "", "next_offset": offset + len(cached_page), "has_more": has_more}
        body = with_secret_access_token(body, app_secrets)
        client = client_from_body(body)
        page = client.search_threads_page(query, limit=limit, page_token=page_token, include_spam_trash=include_system_labels)
        threads = [save_thread(data_root, thread) for thread in page["threads"]]
        if required_label:
            required = required_label.upper()
            threads = [thread for thread in threads if required in {str(label).upper() for label in thread.get("labels", [])}]
        if excluded_labels:
            excluded = {label.upper() for label in excluded_labels}
            threads = [thread for thread in threads if not excluded.intersection({str(label).upper() for label in thread.get("labels", [])})]
        record_audit(
            data_root,
            "gmail.thread_page_synced",
            payload={"count": len(threads), "limit": limit, "query": query, "required_label": required_label, "excluded_labels": excluded_labels, "has_next": bool(page.get("next_page_token"))},
        )
        return 200, {"threads": threads, "source": "gmail", "next_page_token": page.get("next_page_token") or "", "next_offset": offset + len(threads), "has_more": bool(page.get("next_page_token"))}
    if action == "threads.get":
        thread_id = str(body.get("thread_id") or "").strip()
        if body.get("fetch_remote"):
            body = with_secret_access_token(body, app_secrets)
            thread = client_from_body(body).get_thread(thread_id)
            saved = save_thread(data_root, thread)
            record_audit(data_root, "gmail.thread_fetched", subject_id=thread_id, payload={"remote": True})
            return 200, {"thread": saved}
        record_audit(data_root, "gmail.thread_read", subject_id=thread_id, payload={"remote": False})
        return 200, {"thread": get_thread(data_root, thread_id)}
    if action == "threads.mark_read":
        thread = mark_thread_read(data_root, str(body.get("thread_id") or "").strip())
        return 200, {"thread": thread}
    if action == "threads.list_cached":
        return 200, {
            "threads": list_threads(
                data_root,
                str(body.get("query") or ""),
                int(body.get("limit") or 20),
                include_system_labels=bool(body.get("include_system_labels")),
                required_label=str(body.get("required_label") or ""),
                excluded_labels=[str(label) for label in body.get("excluded_labels", []) if str(label)],
                offset=int(body.get("offset") or 0),
            )
        }
    if action == "threads.summarize":
        thread = get_thread(data_root, str(body.get("thread_id") or ""))
        summary = summarize_thread(thread)
        suggestions = [create_suggestion(data_root, item) for item in relationship_suggestions(thread, summary)]
        record_audit(data_root, "gmail.thread_summarized", subject_id=thread["id"], payload={"suggestion_count": len(suggestions)})
        return 200, {"summary": summary, "suggestions": suggestions}
    if action == "suggestions.list":
        return 200, {"suggestions": list_suggestions(data_root, str(body.get("status") or "pending"), int(body.get("limit") or 50))}
    if action == "suggestions.mark_reviewed":
        suggestion_id = str(body.get("suggestion_id") or "").strip()
        decision = str(body.get("decision") or "reviewed").strip()
        return 200, {"decision": mark_suggestion_decision(data_root, suggestion_id, decision, {"local_only": True})}
    if action == "compose.prepare_reply":
        thread = get_thread(data_root, str(body.get("thread_id") or ""))
        draft = prepare_reply(thread, str(body.get("instruction") or ""))
        record_audit(data_root, "gmail.reply_prepared", subject_id=thread["id"], payload={"to_emails": draft["to_emails"], "subject": draft["subject"]})
        return 200, {"draft": draft}
    if action == "send.request_approval":
        approval = create_send_approval(data_root, body)
        return 200, {"approval": approval}
    if action == "send.approved":
        body = with_secret_access_token(body, app_secrets)
        if not str(body.get("access_token") or "").strip() and str(body.get("gmail_client_mode") or "").strip().lower() != "fake":
            raise GmailAppValidationError("A real Gmail access token is required to send email. Reconnect Gmail or send from the authenticated app session.")
        approval = consume_send_approval(data_root, str(body.get("approval_id") or ""))
        sent = client_from_body(body).send_message(
            approval["to_emails"],
            approval["subject"],
            approval["body_text"],
            thread_id=approval["thread_id"],
        )
        record = record_sent_message(data_root, approval["id"], str(sent.get("id") or ""), str(sent.get("threadId") or sent.get("thread_id") or approval["thread_id"]))
        return 200, {"sent": record, "gmail": sent}
    if action == "audit.recent":
        return 200, {"events": list_audit(data_root, int(body.get("limit") or 20))}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        return 200, {"results": reference_search(data_root, body)}
    if action == "references.resolve":
        return 200, reference_resolve(data_root, body)
    if action == "references.summarize":
        return 200, reference_summarize(data_root, body)
    if action == "health.check":
        return 200, health_payload(data_root)
    raise GmailAppValidationError(f"Unknown action `{action}`.")


def with_secret_access_token(body: dict[str, Any], app_secrets: dict[str, str]) -> dict[str, Any]:
    """Return a send body with an access token resolved from the app-scoped OAuth secret when available."""
    if str(body.get("access_token") or "").strip() or str(body.get("gmail_client_mode") or "").strip().lower() == "fake":
        return body
    raw_secret = app_secrets.get("gmail-oauth") or ""
    if not raw_secret:
        return body
    try:
        import json

        secret = json.loads(raw_secret)
    except Exception:
        return body
    if not isinstance(secret, dict):
        return body
    refresh_token = str(secret.get("refresh_token") or "")
    access_token = str(secret.get("access_token") or "")
    if refresh_token:
        refreshed = refresh_access_token(
            client_id=str(secret.get("client_id") or ""),
            client_secret=str(secret.get("client_secret") or ""),
            refresh_token=refresh_token,
        )
        access_token = str(refreshed.get("access_token") or access_token)
    if not access_token:
        return body
    return {**body, "access_token": access_token}


def summarize_thread(thread: dict[str, Any]) -> dict[str, Any]:
    messages = thread.get("messages", [])
    latest = messages[-1] if messages else {}
    body = str(latest.get("body_text") or latest.get("snippet") or thread.get("snippet") or "")
    participants = thread.get("participants", [])
    return {
        "thread_id": thread["id"],
        "subject": thread["subject"],
        "participants": participants,
        "summary": body[:500],
        "relationship_signal": "follow_up" if "follow" in body.lower() or "prossim" in body.lower() else "conversation",
        "suggested_next_step": "Review this exchange and attach it as evidence through a generic reference surface if useful.",
    }


def relationship_suggestions(thread: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions = [
        {
            "thread_id": thread["id"],
            "kind": "activity",
            "title": thread["subject"] or "Gmail conversation",
            "note": summary["summary"],
        }
    ]
    for participant in thread.get("participants", []):
        domain = email_domain(participant)
        if not domain or domain.startswith("gmail."):
            continue
        suggestions.append(
            {
                "thread_id": thread["id"],
                "kind": "contact",
                "title": participant,
                "email": participant,
                "domain": domain,
                "note": f"Observed in Gmail thread `{thread['subject']}`.",
            }
        )
    return suggestions


def reference_search(data_root: Path, body: dict[str, Any]) -> list[dict[str, Any]]:
    entity_type = normalized_reference_type(body)
    query = str(body.get("query") or "").strip()
    limit = int(body.get("limit") or 10)
    if entity_type == "message":
        return [message_reference_result(message) for message in reference_search_messages(data_root, query, limit)]
    if entity_type == "thread":
        return [thread_reference_result(thread) for thread in reference_search_threads(data_root, query, limit)]
    raise GmailAppValidationError(f"Unsupported Gmail reference entity_type `{entity_type}`.")


def reference_resolve(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    entity_type = normalized_reference_type(body)
    entity_id = str(body.get("entity_id") or body.get("id") or "").strip()
    if entity_type == "message":
        return message_reference_result(get_message(data_root, entity_id), exists=True)
    if entity_type == "thread":
        return thread_reference_result(get_thread(data_root, entity_id), exists=True)
    raise GmailAppValidationError(f"Unsupported Gmail reference entity_type `{entity_type}`.")


def reference_summarize(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    entity_type = normalized_reference_type(body)
    entity_id = str(body.get("entity_id") or body.get("id") or "").strip()
    if entity_type == "message":
        message = get_message(data_root, entity_id)
        return {
            "summary": compact_text(message.get("body_text") or message.get("snippet") or "", 700),
            "safe_fields": {
                "entity_type": "message",
                "subject": message["subject"],
                "from_email": message["from_email"],
                "to_emails": message["to_emails"],
                "thread_id": message["thread_id"],
                "received_at": message["received_at"],
            },
            "source_updated_at": message["received_at"],
        }
    if entity_type == "thread":
        thread = get_thread(data_root, entity_id)
        summary = summarize_thread(thread)
        return {
            "summary": summary["summary"],
            "safe_fields": {
                "entity_type": "thread",
                "subject": thread["subject"],
                "participants": thread["participants"],
                "message_count": len(thread.get("messages", [])),
                "updated_at": thread["updated_at"],
                "labels": public_labels(thread.get("labels", [])),
            },
            "source_updated_at": thread["updated_at"],
        }
    raise GmailAppValidationError(f"Unsupported Gmail reference entity_type `{entity_type}`.")


def normalized_reference_type(body: dict[str, Any]) -> str:
    return str(body.get("entity_type") or body.get("type") or "thread").strip().lower()


def thread_reference_result(thread: dict[str, Any], *, exists: bool | None = None) -> dict[str, Any]:
    result = {
        "app_id": "gmail-app",
        "entity_type": "thread",
        "entity_id": thread["id"],
        "title": thread["subject"] or "(no subject)",
        "subtitle": ", ".join(thread.get("participants", [])[:3]),
        "summary": compact_text(thread.get("snippet") or "", 240),
        "source_updated_at": thread["updated_at"],
        "deep_link": f"/apps/gmail-app/?thread_id={thread['id']}",
    }
    if exists is not None:
        result["exists"] = exists
    return result


def message_reference_result(message: dict[str, Any], *, exists: bool | None = None) -> dict[str, Any]:
    result = {
        "app_id": "gmail-app",
        "entity_type": "message",
        "entity_id": message["id"],
        "title": message["subject"] or "(no subject)",
        "subtitle": message["from_email"],
        "summary": compact_text(message.get("snippet") or message.get("body_text") or "", 240),
        "source_updated_at": message["received_at"],
        "deep_link": f"/apps/gmail-app/?thread_id={message['thread_id']}&message_id={message['id']}",
    }
    if exists is not None:
        result["exists"] = exists
    return result


def public_labels(labels: list[str]) -> list[str]:
    hidden = {"SPAM", "TRASH"}
    return [str(label) for label in labels if str(label).upper() not in hidden]


def compact_text(value: str, limit: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: max(0, limit - 3)].rstrip()}..."


def prepare_reply(thread: dict[str, Any], instruction: str) -> dict[str, Any]:
    participants = [item for item in thread.get("participants", []) if item]
    recipient = participants[0] if participants else ""
    subject = str(thread.get("subject") or "")
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    body = instruction.strip() or "Grazie, ti confermo che procedo e ti aggiorno a breve."
    return {
        "thread_id": thread["id"],
        "to_emails": [recipient] if recipient else [],
        "subject": subject,
        "body_text": body,
        "requires_confirmation": True,
    }
