"""Local development UI fixture. Serves built Mail with synthetic mail only.

Run on the approved development port with:
  python3 apps/mail/tests/mail_ui_fixture_server.py --port 8000
No provider, workspace data, credentials or outbound operations are used.
"""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse


DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
ACCOUNT = {"id": "fixture", "provider": "gmail", "email_address": "fixture@example.com", "display_name": "Fixture", "status": "connected"}
def make_threads(count):
    return [{
    "id": f"thread-{index:03}", "connection_id": "fixture", "subject": f"Synthetic message {index:03}",
    "participants": [{"email": "sender@example.com", "name": "Test Sender"}],
    "last_message_at": "2026-10-10T12:00:00Z", "snippet": "Synthetic UI verification content.",
    "unread": index % 2 == 0, "starred": False, "labels": ["inbox"],
    } for index in range(count)]


THREADS = make_threads(251)
DRAFTS = [{
    "id": f"draft-{index:03}", "connection_id": "fixture", "subject": f"Synthetic draft {index:03}",
    "to": [{"email": "recipient@example.com"}], "body_text": "Synthetic draft. Never sent.",
    "status": "draft", "created_at": "2026-10-10T12:00:00Z", "updated_at": "2026-10-10T12:00:00Z",
} for index in range(205)]
for index, status in enumerate(("partially_sent", "unknown", "sending")):
    DRAFTS[index].update(status=status, body_text="Synthetic delivery outcome for UI verification.")
DRAFTS[0].update(to=[{"email": "accepted@example.com"}, {"email": "refused@example.com"}],
                 send_result={"status": "partially_sent", "accepted_recipients": ["accepted@example.com"],
                              "refused_recipients": {"refused@example.com": {"smtp_code": 550}}})


def thread_by_id(thread_id):
    thread = next(item for item in THREADS if item["id"] == thread_id)
    return {**thread, "messages": [{
        "id": "fixture-message", "thread_id": thread_id, "sender": {"email": "sender@example.com"},
        "recipients": [{"email": "fixture@example.com"}], "sent_at": thread["last_message_at"],
        "body_text": "Synthetic reader content.", "has_attachments": False, "labels": thread["labels"],
        "body_html_rendered": '<table style="width:600px"><tr><td><h2>Synthetic reader</h2><p>Visible content with a bounded HTML frame.</p></td></tr></table>',
    }]}


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        route = urlparse(path).path.removeprefix("/apps/mail/")
        target = (DIST / route).resolve()
        if not target.is_relative_to(DIST.resolve()):
            return str(DIST / "missing")
        return str(target)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        action = body.get("action")
        offset, limit = int(body.get("offset", 0)), int(body.get("limit", body.get("max_threads", 200)))
        if action == "connections.list":
            payload = {"items": [ACCOUNT]}
        elif action == "drafts.list":
            drafts = [item for item in DRAFTS if str(body.get("query") or "").casefold() in item["subject"].casefold()]
            payload = {"items": drafts[offset:offset + limit], "total_count": len(drafts)}
        elif action == "drafts.get":
            payload = {"draft": next(item for item in DRAFTS if item["id"] == body["draft_id"])}
        elif action == "threads.get":
            payload = {"thread": thread_by_id(body["thread_id"])}
        elif action in {"messages.mark_read", "labels.modify"}:
            thread = next(item for item in THREADS if item["id"] == body["thread_id"])
            if action == "messages.mark_read":
                thread["unread"] = not body["read"]
            else:
                thread["labels"] = sorted((set(thread["labels"]) - set(body.get("remove", []))) | set(body.get("add", [])))
                thread["unread"] = "unread" in thread["labels"]
                thread["starred"] = "starred" in thread["labels"]
            payload = {"thread": thread_by_id(thread["id"])}
        elif action == "pwa.read_model":
            kind = body["kind"]
            if kind == "mailboxes":
                data = {"items": [ACCOUNT], "folders": []}
            elif kind == "threads":
                items = [item for item in THREADS if str(body.get("query") or "").casefold() in item["subject"].casefold()]
                data = {"items": items[offset:offset + limit], "total_count": len(items), "offset": offset, "limit": limit}
            elif kind == "thread":
                data = {"thread": thread_by_id(body["thread_id"])}
            else:
                data = {"message": thread_by_id("thread-000")["messages"][0]}
            payload = {"revision": "fixture-v1", "payload": {"kind": kind, "data": data}}
        else:
            self.send_error(405, "Fixture accepts display reads and synthetic state updates only")
            return
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--thread-count", type=int, default=251)
    args = parser.parse_args()
    if not 1 <= args.thread_count <= 100000:
        parser.error("thread-count must be between 1 and 100000")
    THREADS = make_threads(args.thread_count)
    with ThreadingHTTPServer(("0.0.0.0", args.port), Handler) as server:
        print(f"Synthetic Mail fixture: http://maverick.localhost:{args.port}/apps/mail/", flush=True)
        server.serve_forever()
