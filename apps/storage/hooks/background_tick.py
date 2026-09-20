"""Storage-owned bounded reconciliation on the existing background scheduler."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from inventory import uses_sqlite
from inventory_operations import recover_operations
from inventory_reconcile import reconcile_inventory

payload = json.loads(sys.stdin.read() or '{}')
data_root = Path(payload['data_root'])
if uses_sqlite(data_root):
    uploaded, generated = Path(payload['uploaded_storage_root']), Path(payload['generated_storage_root'])
    recover_operations(data_root, {'uploaded': uploaded, 'generated': generated})
    result = reconcile_inventory(data_root, uploaded_root=uploaded, generated_root=generated)
else:
    result = {'status': 'migration_required', 'next_due_in_seconds': 300}
print(json.dumps(result))
