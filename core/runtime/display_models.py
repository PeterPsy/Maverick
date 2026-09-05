"""Read-only bounded display projections; never runtime admission or provider state."""
from core.app_sdk.display_models import conditional_display_response

_THREAD_TEXT = ('thread_id', 'runtime_session_id', 'title', 'project_id', 'agent_label', 'source_app_id', 'created_at', 'updated_at', 'last_user_message_at', 'last_completed_response_at')


def thread_display_page(page: dict, known_revision=None) -> dict:
    threads = []
    for item in page.get('threads', page.get('items', [])):
        result = {key: item[key] for key in _THREAD_TEXT if key in item and (item[key] is None or isinstance(item[key], str))}
        result['archived'] = item.get('archived') is True
        threads.append(result)
    pagination = {key: value for key, value in page.get('threads_page', page.get('page', {})).items() if key in ('cursor', 'has_more', 'limit', 'total', 'filtered_total')}
    return conditional_display_response({'kind': 'threads', 'data': {'threads': threads, 'page': pagination}}, known_revision)


def completed_message_display(store, session_id: str, known_revision=None) -> dict:
    # Both scans have hard ceilings. No provider reconciliation or mutation is run.
    turns = [turn for turn in store.list_recent_turns(session_id, limit=50) if turn.status == 'completed']
    completed = {turn.turn_id: turn for turn in turns}
    finals = {}
    for event in store.list_recent_events(session_id, limit=5000):
        if event.turn_id in completed and event.event_type == 'runtime.output.final':
            text = event.payload.get('complete_text') or event.payload.get('text')
            if isinstance(text, str):
                finals[event.turn_id] = (event, text)
    messages = []
    for turn in sorted(turns, key=lambda item: item.created_at):
        final = finals.get(turn.turn_id)
        if final is None:
            continue
        if turn.input_text:
            messages.append({'id': f'{turn.turn_id}:input', 'turn_id': turn.turn_id, 'role': 'user', 'text': turn.input_text, 'created_at': turn.created_at.isoformat()})
        event, text = final
        messages.append({'id': event.event_id, 'turn_id': turn.turn_id, 'role': 'assistant', 'text': text, 'created_at': event.created_at.isoformat()})
    return conditional_display_response({'kind': 'messages', 'data': {'messages': messages}}, known_revision)
