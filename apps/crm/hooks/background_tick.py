"""Core-managed bounded reference refresh; never a detached worker or sender."""
from pathlib import Path
import sys
from core.app_sdk.runtime import read_entrypoint_payload, emit_json
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from service import handle_action, app_events_for_action

payload = read_entrypoint_payload()
_, result = handle_action(payload.data_root, 'crm.integration_tick', {
    '_trusted_surface': 'background_tick', '_app_dependencies': payload.raw.get('app_dependencies', {})})
if result.get('operation_ids'):
    result['app_events'] = app_events_for_action('crm.integration_tick')
emit_json(result)
