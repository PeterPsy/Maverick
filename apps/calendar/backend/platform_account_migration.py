"""Preserve Calendar records when personal accounts share one private store."""

from constants import STATE_FILE
from store import read_state, update_state


def migrate_state(source, root):
    if not (source / STATE_FILE).exists():
        return
    previous = read_state(source)
    initial = not (root / STATE_FILE).exists()

    def merge(state):
        if initial:
            state["view_filter"] = previous["view_filter"]
        for collection in ("connections", "calendars", "sync_state", "events"):
            items = {item["id"]: item for item in state[collection]}
            for item in previous[collection]:
                items.setdefault(item["id"], item)
            state[collection] = list(items.values())
        return state
    update_state(root, merge)
