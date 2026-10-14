"""Restore the prior TLS timer when rolling back the manager's first adoption."""

import json
from pathlib import Path

from core.installation.private_state import write_private

TIMER = 'loopino-wildcard-tls.timer'


def handoff_legacy_timer(manager, private: Path, *, managed: bool, restoring: bool, is_active):
    journal = private / 'legacy-tls-timer.json'
    if managed:
        if not journal.exists():
            state = str(manager.GetUnitFileState(TIMER))
            write_private(journal, {'enabled': state.startswith('enabled'), 'active': is_active(TIMER)})
        manager.StopUnit(TIMER, 'replace')
        manager.DisableUnitFiles([TIMER], False)
    elif restoring and journal.exists():
        previous = json.loads(journal.read_text())
        if previous['enabled']:
            manager.EnableUnitFiles([TIMER], False, False)
        if previous['active']:
            manager.StartUnit(TIMER, 'replace')
        journal.unlink()
