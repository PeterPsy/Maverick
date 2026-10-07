"""Source-owned runtime evidence exposed to app background hooks."""


def runtime_request_id_for_turn(state, session, turn_id):
    streams = getattr(state.runtime_store, "list_app_streams_for_session", None)
    if not streams:
        return ""
    return next((stream.request_id for stream in streams(workspace_id=session.workspace_id, session_id=session.session_id)
                 if stream.source_app_id == session.source_app_id and stream.turn_id == turn_id), "")


def runtime_background_context(state, workspace_id, app_id, *, recovery=False):
    store = getattr(state, "runtime_store", None)
    if store is None:
        return {}
    busy = set()
    recent = []
    requests = []
    sessions = sorted(store.list_sessions(workspace_id), key=lambda x: x.updated_at, reverse=True)
    for session in sessions:
        if session.source_app_id != app_id:
            continue
        streams = getattr(store, "list_app_streams_for_session", None)
        session_streams = []
        if streams:
            session_streams = streams(workspace_id=workspace_id, session_id=session.session_id)
            for stream in session_streams:
                if stream.source_app_id != app_id:
                    continue
                requests.append({"request_id": stream.request_id, "session_id": stream.session_id,
                                 "turn_id": stream.turn_id, "status": stream.status})
        if store.has_turn_with_status(session.session_id, {"queued", "active", "waiting_for_tool_confirmation"}):
            busy.add(session.session_id)
        if recovery and len(recent) < 100 and session.session_kind == "chat_root" and session.thread_visibility == "user":
            for turn in store.list_recent_turns(session.session_id, limit=10):
                if turn.status not in {"completed", "failed", "cancelled"}:
                    continue
                event = store.find_turn_event(turn_id=turn.turn_id, event_type=f"runtime.turn.{turn.status}")
                recent.append({"action": f"runtime.turn.{turn.status}", "turn_id": turn.turn_id,
                    "runtime_request_id": next((stream.request_id for stream in session_streams if stream.source_app_id == app_id and stream.turn_id == turn.turn_id), ""),
                    "runtime_session_id": session.session_id, "turn_status": turn.status,
                    "session_kind": session.session_kind, "thread_visibility": session.thread_visibility,
                    "project_id": session.project_id or "", "input_text": (turn.input_text or "")[:16_000],
                    "output_text": str((event.payload if event else {}).get("output_text") or "")[:16_000],
                    "completed_at": (turn.completed_at or turn.updated_at).isoformat(),
                    "metrics": {"duration_seconds": max(0, ((turn.completed_at or turn.updated_at) - (turn.started_at or turn.created_at)).total_seconds())}})
                if len(recent) >= 100:
                    break
    runs = getattr(state, "inter_agent_store", None)
    if runs is not None:
        for run in runs.list_runs(workspace_id):
            if run.source_app_id == app_id and run.status not in {"completed", "failed", "cancelled"}:
                busy.add(run.root_runtime_session_id)
    result = {"busy_runtime_session_ids": sorted(busy), "runtime_status_complete": True,
              "runtime_request_states": requests}
    if recovery:
        result["recent_terminal_exchanges"] = sorted(recent, key=lambda x: x["completed_at"])
    return result
