"""Health must include the configured provider, even with an existing app database."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('openwa_health', Path(__file__).resolve().parents[1] / 'hooks/health_check.py')
health_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health_hook)
from gateway import GatewayError
from state import configuration, save_configuration


class HealthTests(unittest.TestCase):
    def test_missing_database_is_unhealthy_without_provider_probe(self):
        with tempfile.TemporaryDirectory() as root, patch.object(health_hook, 'check_readiness') as probe:
            self.assertFalse(health_hook.health(root)['ok'])
            probe.assert_not_called()

    def test_existing_database_does_not_hide_provider_outage(self):
        with tempfile.TemporaryDirectory() as root:
            configuration(root)
            with patch.object(health_hook, 'check_readiness', side_effect=GatewayError('Unavailable', 503)):
                self.assertFalse(health_hook.health(root)['ok'])

    def test_probes_configured_gateway_and_accepts_ready_provider(self):
        with tempfile.TemporaryDirectory() as root:
            save_configuration(root, {'url': 'https://example.com', 'configured': True})
            with patch.object(health_hook, 'check_readiness') as probe:
                self.assertTrue(health_hook.health(root)['ok'])
                probe.assert_called_once_with('https://example.com')
