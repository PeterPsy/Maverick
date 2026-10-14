"""Typed path rebasing for an offline, host-operator installation move.

No tenant text, credential envelope or database byte rewriting belongs here.
The operator stops writers and supplies the existing AppStore adapter.
"""

from dataclasses import replace
from pathlib import PurePosixPath


def rebase_installation_path(value: str, *, previous: str, current: str) -> str:
    """Rebase an absolute path within exactly the former installation root."""
    old, new, path = map(PurePosixPath, (previous, current, value))
    if any(not p.is_absolute() or '..' in p.parts for p in (old, new, path)):
        raise ValueError('Installation path fields require absolute paths without traversal')
    if not path.is_relative_to(old):
        return value
    return str(new / path.relative_to(old))


def rebase_app_paths(app_store, *, workspace_ids: list[str], previous: str, current: str) -> list[dict]:
    """Preserve app records/identities and change only declared filesystem fields."""
    planned = []
    groups = [(app_store.list_app_sources(), 'source_path', app_store.save_app_source)]
    for workspace_id in workspace_ids:
        groups.extend([
            (app_store.list_workspace_app_bindings(workspace_id), 'data_root', app_store.save_workspace_app_binding),
            (app_store.list_workspace_local_app_projects(workspace_id), 'project_root', app_store.save_workspace_local_app_project),
        ])
    for records, field, save in groups:
        for record in records:
            before = getattr(record, field)
            after = rebase_installation_path(before, previous=previous, current=current)
            if before != after:
                planned.append((save, replace(record, **{field: after}),
                                {'app_id': record.app_id, 'field': field, 'previous': before, 'current': after}))
    for save, record, _change in planned:
        save(record)
    return [change for _save, _record, change in planned]
