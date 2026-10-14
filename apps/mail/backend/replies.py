"""Message-specific reply recipients and RFC conversation headers."""

from email.utils import getaddresses
import re

from store import get_thread


def reply_context(data_root, connection_id, own_email, thread_id, payload):
    mode = str(payload.get("reply_mode") or "reply")
    if mode not in {"reply", "reply_all"}:
        raise ValueError("reply_mode must be reply or reply_all")
    if not thread_id:
        if payload.get("reply_message_id"):
            raise ValueError("reply_message_id requires thread_id")
        return {"reply_message_id": "", "reply_mode": mode, "in_reply_to": "", "references": []}, [], []
    thread = get_thread(data_root, thread_id, max_body_chars=200)
    if thread["connection_id"] != connection_id:
        raise ValueError("Reply thread belongs to a different mail connection")
    messages = thread.get("messages", [])
    selected_id = str(payload.get("reply_message_id") or "")
    selected = next((item for item in messages if item["id"] == selected_id), None) if selected_id else (messages[-1] if messages else None)
    if not selected:
        raise ValueError("Reply message was not found in this thread")
    headers = {str(name).lower(): value for name, value in selected.get("headers", {}).items()}
    reply_to = [{"name": name, "email": email} for name, email in getaddresses([str(headers.get("reply-to") or "")]) if email]
    primary = reply_to or [selected["sender"]]
    if not reply_to and str(selected["sender"].get("email") or "").casefold() == own_email.casefold():
        primary = selected.get("recipients", [])
    seen = {own_email.casefold()}
    def unique(addresses):
        result = []
        for address in addresses:
            email = str(address.get("email") or "").strip().casefold()
            if email and email not in seen:
                result.append(address)
                seen.add(email)
        return result
    to = unique(primary)
    cc = unique([*selected.get("recipients", []), *selected.get("cc", [])]) if mode == "reply_all" else []
    ids = re.findall(r"<[^<>\s]+>", str(headers.get("message-id") or ""))
    if not ids:
        raise ValueError("Reply message has no valid Message-ID; refresh the thread before creating a reply")
    in_reply_to = ids[0]
    references = re.findall(r"<[^<>\s]+>", str(headers.get("references") or headers.get("in-reply-to") or ""))
    references = list(dict.fromkeys([*references, *ids]))[-50:]
    return {"reply_message_id": selected["id"], "reply_mode": mode, "in_reply_to": in_reply_to, "references": references}, to, cc


def set_conversation_headers(message, draft):
    if draft.get("thread_id") and not draft.get("in_reply_to"):
        raise ValueError("Reply metadata is missing; refresh the thread and create a new reply draft")
    if draft.get("in_reply_to"):
        message["In-Reply-To"] = str(draft["in_reply_to"])
    if draft.get("references"):
        message["References"] = " ".join(draft["references"])
    message["Message-ID"] = str(draft.get("outgoing_message_id") or f"<{draft['id']}@loopino.mail>")
