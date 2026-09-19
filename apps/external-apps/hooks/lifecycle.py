"""App-owned schema/recovery lifecycle, no public process startup side effects."""
from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from external_apps.files import publication_lock
from external_apps.maintenance import cleanup
from external_apps.operations import recover
from external_apps.store import Store

payload = read_entrypoint_payload()
root = Path(payload.data_root)
store = Store(root, str(payload.workspace_id or ""))
with publication_lock(root):
    store.initialize()
    (root / "public/bindings").mkdir(parents=True, exist_ok=True)
    (root / "public/artifacts").mkdir(parents=True, exist_ok=True)
    recover(store)
    cleanup(store)
emit_json({"ok": True, "status": "ready"})
