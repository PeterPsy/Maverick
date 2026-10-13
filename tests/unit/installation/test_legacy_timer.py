from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from core.installation.legacy_timer import handoff_legacy_timer, TIMER


class LegacyTimerTests(unittest.TestCase):
    def test_handoff_and_first_adoption_rollback_restore_prior_automation(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock()
            manager.GetUnitFileState.return_value = 'enabled'
            private = Path(folder)
            handoff_legacy_timer(manager, private, managed=True, restoring=False, is_active=lambda name: True)
            handoff_legacy_timer(manager, private, managed=True, restoring=False, is_active=lambda name: False)
            handoff_legacy_timer(manager, private, managed=False, restoring=True, is_active=lambda name: False)
            manager.EnableUnitFiles.assert_called_once_with([TIMER], False, False)
            manager.StartUnit.assert_called_once_with(TIMER, 'replace')
            manager.GetUnitFileState.assert_called_once()

    def test_an_intentionally_disabled_timer_is_not_enabled_during_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock()
            manager.GetUnitFileState.return_value = 'disabled'
            private = Path(folder)
            handoff_legacy_timer(manager, private, managed=True, restoring=False, is_active=lambda name: False)
            handoff_legacy_timer(manager, private, managed=False, restoring=True, is_active=lambda name: False)
            manager.EnableUnitFiles.assert_not_called()
            manager.StartUnit.assert_not_called()
