"""Initialize or verify the app-owned schema and managed media reader."""
from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from lifecycle import lifecycle
payload = read_entrypoint_payload()
emit_json(lifecycle(Path(payload.data_root),"health_check"))
