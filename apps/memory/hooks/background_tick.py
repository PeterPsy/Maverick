"""Memory queue progress under the platform hook lifecycle, independent of UI."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from maintenance import maintain_memory

payload = json.loads(sys.stdin.read() or '{}')
result = maintain_memory(Path(payload['data_root']), {})
if result['jobs_run']:
    result['app_events'] = [{'type':'maverick.app.data-changed', 'resource':resource} for resource in ('graph','wiki')]
print(json.dumps(result))
