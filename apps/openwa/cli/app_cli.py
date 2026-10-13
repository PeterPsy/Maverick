"""CLI entrypoint for `openwa`."""

from __future__ import annotations

from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from service import handle, event
from gateway import GatewayError


payload = read_entrypoint_payload()
if payload.raw.get("command_id", "").endswith(".provider"):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from provider_cli import handle_provider
    emit_json(handle_provider(payload))
    raise SystemExit(0)
try:
    result = handle(payload, payload.arguments)
    emit_json({'ok': True, **result})
except GatewayError as error:
    result = {'ok': False, 'error': error.code, 'detail': str(error), 'status_code': error.status}
    if payload.arguments.get('action') in {'messages.send', 'messages.reply'} and error.uncertain_send:
        result['app_events'] = [event('notifications')]
    emit_json(result)
