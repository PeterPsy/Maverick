"""Deterministic, completed Markdown/tool history for disposable browser probes."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from core.api.http import json_default
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection


def seed_chat_history(repository: Path, *, turns: int = 3000) -> dict:
    workspace = repository / "workspaces/default"
    session_id = "performance-chat-history"
    runtime = workspace / "runtime/sessions" / session_id
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = start + timedelta(seconds=turns * 4)
    session = RuntimeSessionRecord(
        session_id=session_id, workspace_id="default", agent_id="chat", status="stopped",
        requested_mode=None, effective_mode="sandbox", workspace_root=str(workspace), workdir=str(workspace),
        runtime_root=str(runtime), started_at=start, updated_at=end, ended_at=end, last_progress_at=end,
        source_app_id="chat", thread_title="Performance history fixture", agent_label="Fixture",
    )
    RuntimeSessionJsonCollection(start_path=repository, filename="session.json").update_one(
        {"session_id": session_id}, {"$set": asdict(session)}, upsert=True,
    )
    records = []
    events = []
    for index in range(turns):
        turn_id = f"fixture-turn-{index:05}"
        created = start + timedelta(seconds=index * 4)
        text = f"Fixture request {index:05}"
        records.append(asdict(RuntimeTurnRecord(
            turn_id=turn_id, session_id=session_id, workspace_id="default", status="completed", input_text=text,
            created_at=created, updated_at=created + timedelta(seconds=3), started_at=created,
            completed_at=created + timedelta(seconds=3), failure_reason=None, client_message_id=turn_id,
        )))
        payloads = [
            ("runtime.turn.queued", {"input_text": text, "client_message_id": turn_id}),
            ("runtime.tool_call.completed", {"tool_name": "fixture.inspect", "invocation_id": turn_id,
                "output": "Fixture tool completed without external side effects."}),
            ("runtime.output.final", {"text": f"### Fixture answer {index:05}\n\n"
                "| Item | Value |\n|---|---|\n| Result | Verified |\n\n```python\nresult = 'ready'\n```\n\n"
                "The **completed** response stays accessible while paging through the history."}),
            ("runtime.turn.completed", {}),
        ]
        for offset, (event_type, payload) in enumerate(payloads):
            events.append({"event_id": f"fixture-event-{index * 4 + offset:06}", "session_id": session_id,
                "workspace_id": "default", "turn_id": turn_id, "process_id": None, "plane": "turn",
                "event_type": event_type, "payload": payload, "created_at": created + timedelta(seconds=offset)})
    history = runtime / "events-history"
    history.mkdir()
    for index in range(0, len(events), 500):
        (history / f"{index // 500:06}.json").write_text(json.dumps(events[index:index + 500], default=json_default))
    (runtime / "events.json").write_text(json.dumps(events[-5000:], default=json_default))
    (runtime / "turns.json").write_text(json.dumps(records, default=json_default))
    thread = RuntimeThreadRecord(
        thread_id="performance-chat-thread", workspace_id="default", runtime_session_id=session_id,
        title="Performance history fixture", agent_label="Fixture", agent_type_id="", agent_role_id="",
        source_app_id="chat", system_prompt="", project_id=None, archived=False, availability="free",
        created_at=start, updated_at=end, last_user_message_at=end - timedelta(seconds=4),
        last_completed_response_at=end, last_completed_turn_id=records[-1]["turn_id"],
    )
    WorkspaceRuntimeJsonCollection(start_path=repository, filename="threads.json").update_one(
        {"thread_id": thread.thread_id}, {"$set": asdict(thread)}, upsert=True,
    )
    return {"thread_id": thread.thread_id, "session_id": session_id, "turns": turns, "events": len(events)}
