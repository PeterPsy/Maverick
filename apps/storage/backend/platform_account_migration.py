"""Preserve app-owned Drive connections and inventory across personal accounts."""

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state
from drive_connection_store import STATE_FILE, read_state, update_state
from inventory import load_inventory, uses_sqlite


def migrate_state(source, root):
    for filename in (STATE_FILE, "files.json", "inventory-store.json", "inventory.sqlite", "state.json"):
        if (source / filename).is_symlink():
            raise ValueError("Personal Storage migration sources may not be symlinks.")
    if (source / STATE_FILE).exists():
        previous = read_state(source)
        def merge_connections(state):
            connections = {item["id"]: item for item in state["connections"]}
            for item in previous["connections"]:
                connections.setdefault(item["id"], item)
            state["connections"] = list(connections.values())
            return state
        update_state(root, merge_connections)
    if (source / "files.json").exists() or (source / "inventory-store.json").exists():
        previous = load_inventory(source)
        if uses_sqlite(source) and not (root / "files.json").exists() and not (root / "inventory-store.json").exists():
            from inventory_migration import initialize_inventory
            initialize_inventory(root)
        if uses_sqlite(root):
            from inventory_sqlite import InventoryIndex
            index = InventoryIndex(root)
            with index.transaction(write=True) as db:
                for item in previous["files"]:
                    if index.get(db, item["file_id"]) is None:
                        index.put_file(db, item)
                for item in previous.get("directories", []):
                    if not db.execute("SELECT 1 FROM directories WHERE directory_id=?", (item["id"],)).fetchone():
                        index.put_directory(db, item)
        else:
            def merge_inventory(state):
                for collection, key in (("files", "file_id"), ("directories", "id")):
                    items = {item[key]: item for item in state.get(collection, [])}
                    for item in previous.get(collection, []):
                        items.setdefault(item[key], item)
                    state[collection] = list(items.values())
                state.setdefault("schema_version", "1")
                return state
            update_json_state(root, "files.json", merge_inventory)
    if (source / "state.json").exists() and not (root / "state.json").exists():
        write_json_state(root, "state.json", read_json_state(source, "state.json"))
