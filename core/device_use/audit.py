"""Authorized, paginated Device Use audit over persistent runtime history."""

import json

from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.transcript_access import resolve_authorized_transcript_thread
from core.runtime.transcript_history import read_runtime_event_history
from core.runtime.transcript_payloads import bounded_int
from core.runtime.transcript_safety import redact_transcript_text
from core.runtime.private_payload_models import RuntimePrivatePayloadError
from core.runtime.usage_read import read_runtime_usage


def read_device_use_audit(store, *, context, thread_id, limit=30, before_cursor=None, usage_store=None):
    thread, session, _relation = resolve_authorized_transcript_thread(store, context=context, thread_id=thread_id)
    bounded = bounded_int(limit, minimum=1, maximum=50, field="limit")
    history = read_runtime_event_history(store, session.session_id)
    calls = _calls(history.events)
    cursor_found = before_cursor is None
    end = len(calls)
    if before_cursor:
        for index, call in enumerate(calls):
            if call["audit_id"] == before_cursor:
                end = index
                cursor_found = True
                break
        if not cursor_found:
            raise RuntimeTranscriptValidationError("audit_cursor_not_found")
    start = max(0, end - bounded)
    page = calls[start:end]
    usage = read_runtime_usage(store, usage_store=usage_store, context=context, thread_id=thread_id)["usage"] if usage_store is not None else None
    return {"thread_id": thread.thread_id, "calls": page, "usage": usage,
            "page": {"has_more_before": start > 0, "before_cursor": page[0]["audit_id"] if start > 0 else None},
            "history_complete": history.complete, "coverage": "native_lifecycle_and_available_encrypted_evidence",
            "turns": _turn_metrics(store.list_turns(session.session_id), calls),
            "content_trust": "untrusted_conversation_data"}


def read_device_use_call(store, *, archive, context, thread_id, turn_id, call_id, offset=0, max_chars=12000):
    _thread, session, relation = resolve_authorized_transcript_thread(store, context=context, thread_id=thread_id)
    if relation not in {"owner", "admin"}:
        raise RuntimeTranscriptAccessError("device_use_evidence_owner_required", status_code=403)
    offset = bounded_int(offset, minimum=0, maximum=2_147_483_647, field="offset")
    max_chars = bounded_int(max_chars, minimum=1, maximum=12000, field="max_chars")
    events = read_runtime_event_history(store, session.session_id).events
    selected = [event for event in events if event.event_type == "runtime.device_use.evidence"
                and event.turn_id == turn_id and event.payload.get("call_id") == call_id]
    if not selected or archive is None:
        raise RuntimeTranscriptAccessError("device_use_evidence_unavailable", status_code=404)
    try:
        documents = [archive.read(session=session, ref=event.payload["evidence_ref"]) for event in selected]
    except (RuntimePrivatePayloadError, ValueError, KeyError):
        raise RuntimeTranscriptAccessError("device_use_evidence_unavailable", status_code=404) from None
    arguments = next((document.get("arguments") for document in documents if "arguments" in document), None)
    terminal = documents[-1]
    safe = {"arguments": arguments, "result": terminal.get("result"), "journal": terminal.get("journal"),
            "has_image": bool(terminal.get("image_refs")), "typed_text_withheld": True}
    text = redact_transcript_text(json.dumps(safe, ensure_ascii=False, default=str, indent=2))
    end = min(len(text), offset + max_chars)
    return {"thread_id": thread_id, "turn_id": turn_id, "call_id": call_id,
            "content": text[offset:end], "content_char_count": len(text),
            "offset": offset, "has_more": end < len(text), "next_offset": end if end < len(text) else None,
            "has_image": bool(terminal.get("image_refs")),
            "content_trust": "untrusted_native_observation_data"}


def device_use_call_image(store, *, archive, context, thread_id, turn_id, call_id):
    _thread, session, relation = resolve_authorized_transcript_thread(store, context=context, thread_id=thread_id)
    if relation not in {"owner", "admin"}:
        raise RuntimeTranscriptAccessError("device_use_evidence_owner_required", status_code=403)
    events = read_runtime_event_history(store, session.session_id).events
    event = next((event for event in reversed(events) if event.event_type == "runtime.device_use.evidence"
                  and event.turn_id == turn_id and event.payload.get("call_id") == call_id
                  and event.payload.get("has_image") is True), None)
    if event is None or archive is None:
        raise RuntimeTranscriptAccessError("device_use_image_unavailable", status_code=404)
    try:
        return archive.image(session=session, document=archive.read(session=session, ref=event.payload["evidence_ref"]))
    except (RuntimePrivatePayloadError, ValueError, KeyError):
        raise RuntimeTranscriptAccessError("device_use_image_unavailable", status_code=404) from None


def _calls(events):
    grouped = {}
    for event in events:
        payload = event.payload
        is_evidence = event.event_type == "runtime.device_use.evidence"
        is_call = event.event_type in {"runtime.tool_call.started", "runtime.tool_call.completed", "runtime.tool_call.failed"} and payload.get("tool_kind") == "device_use"
        if not is_evidence and not is_call:
            continue
        call_id = payload.get("call_id") or payload.get("tool_call_id")
        if not isinstance(call_id, str) or not event.turn_id:
            continue
        key = (event.turn_id, call_id)
        tool = payload.get("tool_name") if is_evidence else payload.get("name")
        item = grouped.setdefault(key, {"audit_id": f"{event.turn_id}:{call_id}", "turn_id": event.turn_id,
                                        "call_id": call_id, "tool_name": tool, "action": payload.get("action"),
                                        "started_at": event.created_at.isoformat(), "status": "started",
                                        "evidence_available": False})
        if is_evidence:
            item["tool_name"] = tool
            item["action"] = payload.get("action")
            item["evidence_available"] = True
            item["has_image"] = payload.get("has_image") is True or item.get("has_image", False)
        status = payload.get("status") if is_evidence else event.event_type.rsplit(".", 1)[-1]
        if status in {"completed", "failed", "execution_unknown"} and item["status"] != "execution_unknown":
            item["status"] = status
            item["completed_at"] = event.created_at.isoformat()
        for name in ["native_duration_ms", "native_user_wait_ms", "result_valid", "native_success", "outcome_state", "failure_reason_code", "image_bytes", "bridge_end_to_end_ms", "project_stage", "provider_observation_delivery_ms", "result_text_char_count"]:
            if name in payload and (payload[name] is not None or name not in item):
                item[name] = payload[name]
    return list(grouped.values())


def _turn_metrics(turns, calls):
    result = []
    for turn in turns:
        selected = [item for item in calls if item["turn_id"] == turn.turn_id]
        if not selected:
            continue
        finish = getattr(turn, "completed_at", None)
        elapsed = max(0, (finish - turn.created_at).total_seconds() * 1000) if finish else None
        native = _measured_sum(selected, "native_duration_ms")
        user_wait = _measured_sum(selected, "native_user_wait_ms")
        bridge = _measured_sum(selected, "bridge_end_to_end_ms")
        images_known = all("has_image" in item for item in selected)
        image_bytes = _measured_sum(selected, "image_bytes")
        groups = {}
        for item in selected:
            key = f"{item.get('tool_name')}.{item.get('action')}"
            groups.setdefault(key, []).append(item)
        by_action = {key: {"call_count": len(group),
                           "native_duration_ms": _measured_sum(group, "native_duration_ms"),
                           "native_user_wait_ms": _measured_sum(group, "native_user_wait_ms")}
                     for key, group in groups.items()}
        coverage = {field: sum(item.get(field) is not None for item in selected)
                    for field in ["native_duration_ms", "native_user_wait_ms", "bridge_end_to_end_ms", "image_bytes", "provider_observation_delivery_ms", "result_text_char_count"]}
        coverage["image_count"] = sum("has_image" in item for item in selected)
        unavailable = ["model_processing_ms", "image_token_breakdown"]
        unavailable.extend(field for field, count in coverage.items() if count < len(selected))
        result.append({"turn_id": turn.turn_id, "started_at": turn.created_at.isoformat(),
                       "completed_at": finish.isoformat() if finish else None,
                       "elapsed_ms": elapsed, "native_duration_ms": native,
                       "native_user_wait_ms": user_wait,
                       "native_execution_ms": max(0, native - user_wait) if native is not None and user_wait is not None else None,
                       "outside_native_ms": max(0, elapsed - native) if elapsed is not None and native is not None else None,
                       "outside_bridge_ms": max(0, elapsed - bridge) if elapsed is not None and bridge is not None else None,
                       "call_count": len(selected), "failed_count": sum(item["status"] == "failed" for item in selected),
                       "execution_unknown_count": sum(item["status"] == "execution_unknown" for item in selected),
                       "uncertain_outcome_count": sum(item.get("outcome_state") in {"indeterminate", "dispatched_unverified", "suspected_noop", "partial"} for item in selected),
                       "invalid_result_count": sum(item.get("result_valid") is False for item in selected),
                       "image_count": sum(item.get("has_image") is True for item in selected) if images_known else None,
                       "image_bytes": int(image_bytes) if image_bytes is not None else None,
                       "bridge_end_to_end_ms": bridge,
                       "provider_observation_delivery_ms": _measured_sum(selected, "provider_observation_delivery_ms"),
                       "result_text_char_count": _measured_sum(selected, "result_text_char_count"),
                       "bridge_overhead_ms": sum(max(0, float(item["bridge_end_to_end_ms"]) - float(item["native_duration_ms"])) for item in selected) if native is not None and bridge is not None else None,
                       "by_action": by_action,
                       "project_checkpoints": [{"stage": item["project_stage"], "recorded_at": item.get("completed_at")} for item in selected if item.get("project_stage")],
                       "measured_user_wait": "native_approvals_and_project_picker",
                       "unavailable_metrics": unavailable, "metric_measured_call_counts": coverage,
                       "usage_source": "core_usage",
                       "timing_coverage": "recorded_turn_and_native_clocks; outside_native_is_not_model_time"})
    return result


def _measured_sum(calls, field):
    values = [item.get(field) for item in calls]
    return sum(float(value) for value in values) if all(value is not None for value in values) else None
