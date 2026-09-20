"""Explicit Usage adapter selection, independent of the general document backend."""

from pathlib import Path

from core.usage.handoff import USAGE_ROOT, selected_adapter, usage_fence
from core.usage.sqlite_store import UsageSqliteStore
from core.usage.store import UsageCollections, UsageDocumentStore, UsageStore


def build_usage_store(repository_root: Path, collections: UsageCollections) -> UsageStore:
    root = repository_root / USAGE_ROOT
    adapter = selected_adapter()
    with usage_fence(root, expected=adapter):
        if adapter == 'document':
            return UsageDocumentStore(collections, handoff_root=root)
        store = UsageSqliteStore(root / 'usage.sqlite', handoff_root=root)
        with store.connection():
            pass  # Fail startup on a missing/unsupported database; never migrate implicitly.
        return store
