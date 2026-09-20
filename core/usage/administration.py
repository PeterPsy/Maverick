"""Declared operator surfaces for the Usage persistence owner."""

from pathlib import Path

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.usage import migration

MIGRATION_SCHEMA = {'type': 'object', 'properties': {
    'phase': {'type': 'string', 'enum': ['prepare', 'validate', 'cutover', 'rollback', 'backup']},
    'migration_id': {'type': 'string'},
}, 'required': ['phase'], 'additionalProperties': False}


def usage_migration(repository_root: Path, arguments: dict) -> dict:
    """Prepare and cut over only in an operator-drained maintenance window."""
    phase = arguments.get('phase')
    if phase == 'validate':
        return migration.validate(repository_root, str(arguments.get('migration_id') or ''))
    if phase == 'backup':
        return migration.backup(repository_root)
    if phase not in {'prepare', 'cutover', 'rollback'}:
        raise ValueError('Unknown Usage migration phase.')
    settings = ControlStoreSettings.from_environment(repository_root=repository_root)
    collections = build_control_plane_collections(settings).usage
    if phase == 'prepare':
        return migration.prepare(repository_root, collections)
    if phase == 'cutover':
        return migration.cutover(repository_root, collections, str(arguments.get('migration_id') or ''))
    return migration.rollback(repository_root, collections)
