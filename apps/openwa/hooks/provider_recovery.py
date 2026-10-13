"""Recover only an explicitly enabled default-workspace local provider."""
from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / 'backend'))
sys.path.insert(0, str(APP_ROOT / 'provider'))
from provider_service import ProviderServiceError, ensure_running


def recover(payload):
    expected = APP_ROOT.parents[1] / 'workspaces/default/data/openwa'
    if payload.workspace_id != 'default' or Path(payload.data_root).resolve() != expected.resolve():
        return {'ok': True, 'skipped': True, 'next_due_in_seconds': 300}
    if payload.raw.get('surface') not in {'backend_recovery', 'background_tick'}:
        return {'ok': False, 'error': 'provider_hook_scope_mismatch', 'next_due_in_seconds': 300}
    try:
        return {**ensure_running(), 'next_due_in_seconds': 30}
    except (ProviderServiceError, OSError):
        return {'ok': False, 'error': 'provider_recovery_failed', 'next_due_in_seconds': 60}


if __name__ == '__main__':
    emit_json(recover(read_entrypoint_payload()))
