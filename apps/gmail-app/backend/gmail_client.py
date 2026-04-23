"""Gmail API adapters for Gmail App."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
import base64
import json
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from errors import GmailConnectionError, GmailAppValidationError
from gmail_models import GmailMessage, GmailThread, clean_email, extract_email_addresses, has_excluded_system_label, utc_now


class GmailClient(Protocol):
    def search_threads(self, query: str, limit: int = 10, *, include_spam_trash: bool = False) -> list[GmailThread]:
        """Return Gmail threads matching a user query."""

    def search_threads_page(self, query: str, limit: int = 50, *, page_token: str = "", include_spam_trash: bool = False) -> dict[str, Any]:
        """Return one Gmail thread result page plus the provider pagination token."""

    def get_thread(self, thread_id: str) -> GmailThread:
        """Return one Gmail thread."""

    def send_message(self, to_emails: list[str], subject: str, body_text: str, thread_id: str = "", attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Send one message and return Gmail metadata."""


class FakeGmailClient:
    """Deterministic Gmail client for tests and local dry-run use."""

    def __init__(self, threads: list[GmailThread] | None = None) -> None:
        self.threads = threads or sample_threads()
        self.sent_messages: list[dict[str, Any]] = []

    def search_threads(self, query: str, limit: int = 10, *, include_spam_trash: bool = False) -> list[GmailThread]:
        page = self.search_threads_page(query, limit=limit, include_spam_trash=include_spam_trash)
        return list(page["threads"])

    def search_threads_page(self, query: str, limit: int = 50, *, page_token: str = "", include_spam_trash: bool = False) -> dict[str, Any]:
        needle = query.strip().lower()
        matches = [
            thread
            for thread in self.threads
            if (include_spam_trash or not has_excluded_system_label(thread.labels))
            and fake_thread_matches_query(thread, needle)
        ]
        page_size = max(1, min(limit, 100))
        offset = max(0, int(page_token or "0")) if str(page_token or "").isdigit() else 0
        page = matches[offset : offset + page_size]
        next_offset = offset + page_size
        return {
            "threads": page,
            "next_page_token": str(next_offset) if next_offset < len(matches) else "",
        }

    def get_thread(self, thread_id: str) -> GmailThread:
        for thread in self.threads:
            if thread.id == thread_id:
                return thread
        raise GmailAppValidationError(f"Thread `{thread_id}` was not found.")

    def send_message(self, to_emails: list[str], subject: str, body_text: str, thread_id: str = "", attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        attachments = attachments or []
        sent = {
            "id": f"fake_msg_{len(self.sent_messages) + 1}",
            "thread_id": thread_id or f"fake_thread_sent_{len(self.sent_messages) + 1}",
            "labelIds": ["SENT"],
            "to_emails": to_emails,
            "subject": subject,
            "body_text": body_text,
            "attachments": [
                {
                    "filename": str(item.get("filename") or ""),
                    "content_type": str(item.get("content_type") or ""),
                    "size_bytes": len(item.get("content_bytes") or b""),
                }
                for item in attachments
            ],
        }
        self.sent_messages.append(sent)
        return sent


class HttpGmailClient:
    """Small Gmail REST client using an access token supplied by core secrets."""

    def __init__(self, access_token: str) -> None:
        if not access_token:
            raise GmailConnectionError("Gmail access token is required.")
        self.access_token = access_token

    def search_threads(self, query: str, limit: int = 10, *, include_spam_trash: bool = False) -> list[GmailThread]:
        page = self.search_threads_page(query, limit=limit, include_spam_trash=include_spam_trash)
        return list(page["threads"])

    def search_threads_page(self, query: str, limit: int = 50, *, page_token: str = "", include_spam_trash: bool = False) -> dict[str, Any]:
        clean_query = query.strip() if include_spam_trash else append_spam_trash_exclusions(query)
        params_payload = {
            "q": clean_query,
            "maxResults": max(1, min(limit, 100)),
            "includeSpamTrash": "true" if include_spam_trash else "false",
        }
        if page_token:
            params_payload["pageToken"] = page_token
        params = urlencode(params_payload)
        payload = self._request_json(f"https://gmail.googleapis.com/gmail/v1/users/me/threads?{params}")
        threads = []
        for item in payload.get("threads", []):
            thread = self.get_thread(str(item.get("id") or ""))
            if include_spam_trash or not has_excluded_system_label(thread.labels):
                threads.append(thread)
        return {"threads": threads, "next_page_token": str(payload.get("nextPageToken") or "")}

    def get_thread(self, thread_id: str) -> GmailThread:
        if not thread_id:
            raise GmailAppValidationError("thread_id is required.")
        payload = self._request_json(f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{quote(thread_id)}?format=full")
        return thread_from_gmail_payload(payload)

    def send_message(self, to_emails: list[str], subject: str, body_text: str, thread_id: str = "", attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        message = EmailMessage()
        message["To"] = ", ".join(to_emails)
        message["Subject"] = subject
        message.set_content(body_text)
        for attachment in attachments or []:
            maintype, _, subtype = str(attachment.get("content_type") or "application/octet-stream").partition("/")
            if not subtype:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(
                attachment.get("content_bytes") or b"",
                maintype=maintype,
                subtype=subtype,
                filename=str(attachment.get("filename") or "attachment"),
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        return self._request_json(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            method="POST",
            body=body,
        )

    def _request_json(self, url: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except Exception as error:  # pragma: no cover - network path
            raise GmailConnectionError(f"Gmail API request failed: {error}") from error


def client_from_body(body: dict[str, Any]) -> GmailClient:
    mode = str(body.get("gmail_client_mode") or "").strip().lower()
    if mode == "fake" or body.get("fake_threads"):
        return FakeGmailClient(threads_from_payload(body.get("fake_threads") or []))
    access_token = str(body.get("access_token") or "").strip()
    if access_token:
        return HttpGmailClient(access_token)
    return FakeGmailClient()


def append_spam_trash_exclusions(query: str) -> str:
    query = query.strip()
    exclusions = "-in:spam -in:trash"
    if not query:
        return exclusions
    return f"{query} {exclusions}"


def fake_thread_matches_query(thread: GmailThread, needle: str) -> bool:
    if not needle:
        return True
    labels = {str(label).upper() for label in thread.labels or []}
    checks = {
        "in:spam": "SPAM" in labels,
        "in:sent": "SENT" in labels,
        "in:inbox": "INBOX" in labels,
        "is:important": "IMPORTANT" in labels,
        "is:starred": "STARRED" in labels,
        "category:promotions": "CATEGORY_PROMOTIONS" in labels,
        "category:updates": "CATEGORY_UPDATES" in labels,
    }
    if needle in checks:
        return checks[needle]
    if needle == "in:inbox -category:promotions -category:updates":
        return "INBOX" in labels and not {"CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "SPAM", "TRASH"}.intersection(labels)
    return (
        needle in thread.subject.lower()
        or needle in thread.snippet.lower()
        or any(needle in participant.lower() for participant in thread.participants)
    )


def threads_from_payload(items: list[dict[str, Any]]) -> list[GmailThread]:
    threads: list[GmailThread] = []
    for item in items:
        messages = [
            GmailMessage(
                id=str(message.get("id") or ""),
                thread_id=str(message.get("thread_id") or item.get("id") or ""),
                from_email=clean_email(str(message.get("from_email") or message.get("from") or "")),
                to_emails=[clean_email(str(email)) for email in message.get("to_emails", [])],
                subject=str(message.get("subject") or item.get("subject") or ""),
                snippet=str(message.get("snippet") or ""),
                body_text=str(message.get("body_text") or ""),
                received_at=normalize_gmail_timestamp(message.get("received_at")),
                is_unread=bool(message.get("is_unread")),
            )
            for message in item.get("messages", [])
        ]
        participants = sorted({email for message in messages for email in [message.from_email, *message.to_emails] if email})
        threads.append(
            GmailThread(
                id=str(item.get("id") or ""),
                subject=str(item.get("subject") or ""),
                participants=participants or [clean_email(str(value)) for value in item.get("participants", [])],
                snippet=str(item.get("snippet") or " ".join(message.snippet for message in messages)).strip(),
                updated_at=normalize_gmail_timestamp(item.get("updated_at") or latest_message_timestamp(messages)),
                messages=messages,
                is_unread=bool(item.get("is_unread")) or any(message.is_unread for message in messages),
                labels=[str(label) for label in item.get("labels", [])],
            )
        )
    return threads


def thread_from_gmail_payload(payload: dict[str, Any]) -> GmailThread:
    thread_id = str(payload.get("id") or "")
    messages: list[GmailMessage] = []
    for item in payload.get("messages", []):
        headers = {header.get("name", "").lower(): header.get("value", "") for header in item.get("payload", {}).get("headers", [])}
        body_text = extract_body_text(item.get("payload", {}))
        to_emails = extract_email_addresses(headers.get("to", ""))
        messages.append(
            GmailMessage(
                id=str(item.get("id") or ""),
                thread_id=thread_id,
                from_email=clean_email(headers.get("from", "")),
                to_emails=to_emails,
                subject=str(headers.get("subject") or ""),
                snippet=str(item.get("snippet") or ""),
                body_text=body_text,
                received_at=normalize_gmail_timestamp(item.get("internalDate")),
                is_unread="UNREAD" in item.get("labelIds", []),
            )
        )
    participants = sorted({email for message in messages for email in [message.from_email, *message.to_emails] if email})
    subject = next((message.subject for message in messages if message.subject), "")
    snippet = " ".join(message.snippet for message in messages if message.snippet).strip()
    labels = sorted({label for item in payload.get("messages", []) for label in item.get("labelIds", [])})
    return GmailThread(id=thread_id, subject=subject, participants=participants, snippet=snippet, updated_at=latest_message_timestamp(messages), messages=messages, is_unread=any(message.is_unread for message in messages), labels=labels)


def latest_message_timestamp(messages: list[GmailMessage]) -> str:
    timestamps = [normalize_gmail_timestamp(message.received_at) for message in messages if message.received_at]
    return max(timestamps) if timestamps else utc_now()


def normalize_gmail_timestamp(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return utc_now()
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw) / 1000, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return utc_now()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return utc_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_body_text(part: dict[str, Any]) -> str:
    body = part.get("body", {})
    data = body.get("data")
    if data:
        try:
            return base64.urlsafe_b64decode(str(data).encode("ascii")).decode("utf-8", errors="replace")
        except Exception:
            return ""
    for child in part.get("parts", []) or []:
        text = extract_body_text(child)
        if text:
            return text
    return ""


def sample_threads() -> list[GmailThread]:
    message = GmailMessage(
        id="msg_demo_1",
        thread_id="thread_demo_1",
        from_email="mario.rossi@acme.example",
        to_emails=["user@company.example"],
        subject="Allineamento progetto CRM",
        snippet="Possiamo sentirci domani per definire il follow-up commerciale.",
        body_text="Ciao, possiamo sentirci domani per definire il follow-up commerciale e i prossimi passi con Acme.",
        received_at="2026-04-21T09:00:00Z",
    )
    return [
        GmailThread(
            id="thread_demo_1",
            subject="Allineamento progetto CRM",
            participants=["mario.rossi@acme.example", "user@company.example"],
            snippet=message.snippet,
            updated_at="2026-04-21T09:00:00Z",
            messages=[message],
        )
    ]
