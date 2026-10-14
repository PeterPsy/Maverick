"""Offline relocation changes typed path fields, preserving tenant identities."""
from dataclasses import dataclass
from unittest import TestCase
from core.installation.relocation import rebase_app_paths, rebase_installation_path

OLD = '/previous/loopino'
NEW = '/root/projects/loopino'


@dataclass(frozen=True)
class Source:
    app_id: str
    source_path: str
    description: str
    created_at: str = 'unchanged'


@dataclass(frozen=True)
class Binding:
    app_id: str
    data_root: str
    status: str = 'enabled'
    binding_id: str = 'same-binding'


class RelocationTests(TestCase):
    def test_only_a_complete_root_component_is_rebased(self):
        for before, after in [(OLD,NEW),(OLD+'/apps/a',NEW+'/apps/a'),(OLD+'-else/a',OLD+'-else/a')]:
            self.assertEqual(rebase_installation_path(before,previous=OLD,current=NEW),after)
        for value in ['relative/path',OLD+'/../secret']:
            with self.assertRaises(ValueError):
                rebase_installation_path(value,previous=OLD,current=NEW)

    def test_nested_new_prefix_is_idempotent(self):
        previous = '/projects/loopino'
        current = '/root/projects/loopino'
        moved = rebase_installation_path(previous + '/apps/a', previous=previous, current=current)
        self.assertEqual(moved, current + '/apps/a')
        self.assertEqual(rebase_installation_path(moved, previous=previous, current=current), moved)

    def test_adapter_rebase_preserves_text_status_timestamps_and_ids(self):
        source=Source('a',OLD+'/apps/a','A historical note mentions '+OLD)
        binding=Binding('a',OLD+'/workspaces/default/data/a')
        class Store:
            def __init__(self): self.sources=[source];self.bindings=[binding]
            def list_app_sources(self): return self.sources
            def list_workspace_app_bindings(self,workspace): return self.bindings
            def list_workspace_local_app_projects(self,workspace): return []
            def save_app_source(self,record): self.sources=[record]
            def save_workspace_app_binding(self,record): self.bindings=[record]
            def save_workspace_local_app_project(self,record): raise AssertionError('No local projects')
        store=Store()
        self.assertEqual(len(rebase_app_paths(store,workspace_ids=['default'],previous=OLD,current=NEW)),2)
        self.assertEqual(store.sources[0],Source('a',NEW+'/apps/a',source.description))
        self.assertEqual(store.bindings[0],Binding('a',NEW+'/workspaces/default/data/a'))
        self.assertEqual(rebase_app_paths(store,workspace_ids=['default'],previous=OLD,current=NEW),[])
