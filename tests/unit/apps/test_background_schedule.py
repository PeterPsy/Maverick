"""Deadlines prevent process launches, recover failures, and discard removed owners."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.apps.background_schedule import BackgroundHookSchedule
from core.apps.runtime_event_hooks import dispatch_workspace_app_background_hooks


class BackgroundScheduleTests(unittest.TestCase):
    def test_deadline_is_checked_before_surface_resolution_or_process_spawn(self):
        now = [100.0]
        schedule = BackgroundHookSchedule(clock=lambda: now[0])
        binding = SimpleNamespace(app_id='sample', status='enabled', updated_at='v1')
        state = SimpleNamespace(app_store=object())
        args = dict(workspace_id='workspace', hook_name='background_tick', action='background.tick', due_schedule=schedule)
        with patch('core.apps.runtime_event_hooks.enabled_workspace_app_bindings', return_value=[binding]), \
             patch('core.apps.runtime_event_hooks.resolve_workspace_app_surface', return_value=(Path('/app'), object())) as resolve, \
             patch('core.apps.runtime_event_hooks._dispatch_workspace_app_background_hook', return_value={'next_due_in_seconds': 300}) as spawn:
            dispatch_workspace_app_background_hooks(state, **args)
            now[0] += 299
            self.assertEqual(dispatch_workspace_app_background_hooks(state, **args), [])
            resolve.assert_called_once()
            spawn.assert_called_once()
            now[0] += 1
            dispatch_workspace_app_background_hooks(state, **args)
            self.assertEqual(spawn.call_count, 2)
            binding.updated_at = 'v2'
            dispatch_workspace_app_background_hooks(state, **args)
            self.assertEqual(spawn.call_count, 3)

    def test_intervals_are_bounded_and_disabled_owners_are_forgotten(self):
        schedule = BackgroundHookSchedule(clock=lambda: 100)
        key = ('workspace', 'sample', 'background_tick')
        for invalid in (float('nan'), 'immediate', True):
            schedule.complete(key, '', {'next_due_in_seconds': invalid})
            self.assertEqual(schedule.next_delay(), 15)
        schedule.complete(key, '', {'next_due_in_seconds': 0})
        self.assertEqual(schedule.next_delay(), 1)
        schedule.prune_apps('workspace', set())
        self.assertFalse(schedule.entries)
        schedule.complete(key, '', None)
        schedule.prune_workspaces(set())
        self.assertFalse(schedule.entries)
