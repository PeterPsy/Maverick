"""Read-only app storage health; public reachability is separately reported."""
from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from external_apps.store import Store

payload = read_entrypoint_payload()
try:
    store = Store(Path(payload.data_root), str(payload.workspace_id or ""))
    store.assert_workspace()
    with store.connection(readonly=True) as db:
        healthy = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    emit_json({"ok": healthy, "status": "ready" if healthy else "failed"})
except Exception:
    emit_json({"ok": False, "status": "failed"})
