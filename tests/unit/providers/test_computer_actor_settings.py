"""Workspace isolation, persistence, catalog admission and settings API."""

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from core.api.control_store import ControlStoreSettings, build_control_plane_collections, control_plane_collection_specs
from core.api.session_api import RequestSession
from core.api.settings_api import handle_settings_api
from core.authorization.errors import AuthorizationError
from core.providers.computer_actor_factory import create_computer_actor
from core.providers.computer_actor_settings import (
    computer_actor_selection, computer_actor_settings_payload, configure_computer_actor, validate_computer_actor_selection,
)
from core.providers.errors import ProviderSelectionError
from core.providers.models import ProviderModelOption, ProviderReasoningOption
from core.providers.provider_codex import CodexProviderAdapter
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.shared.in_memory_collection import InMemoryCollection


class CatalogAdapter:
    def model_options(self, **_kwargs):
        return [ProviderModelOption(model, label, None, 'medium', [
            ProviderReasoningOption('low', 'Low'), ProviderReasoningOption('medium', 'Medium')],
            input_modalities=modalities) for model, label, modalities in (
                ('gpt-6-luna', 'Luna', ['text', 'image']),
                ('gpt-6-sol', 'Sol', ['text', 'image']),
                ('gpt-6.1-sol', 'Sol 6.1', ['text', 'image']),
                ('text-only', 'Text only', ['text']))]

    def validate_model_settings(self, model, effort):
        if effort not in {'low', 'medium'}:
            raise ProviderSelectionError('unsupported effort')
        return model, effort


class ComputerActorSettingsTests(unittest.TestCase):
    def setUp(self):
        self.store = ProviderDocumentStore(ProviderCollections(InMemoryCollection(), InMemoryCollection(),
            InMemoryCollection(), task_selections=InMemoryCollection()))
        self.adapter = CatalogAdapter()
        self.patcher = patch('core.providers.computer_actor_settings.CodexProviderAdapter', return_value=self.adapter)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def configure(self, **overrides):
        values = dict(workspace_id='workspace-a', provider_id='codex', model_id='gpt-6-sol', reasoning_effort=None)
        values.update(overrides)
        return configure_computer_actor(self.store, **values)

    def test_default_is_sol_mid_without_changing_chat_or_hosted_selection(self):
        selection = computer_actor_selection(self.store, 'workspace-a')
        self.assertEqual((selection.provider_id, selection.model_id, selection.reasoning_effort), ('codex', 'gpt-6.1-sol', 'medium'))
        self.assertIsNone(self.store.get_provider_selection('workspace-a'))
        self.assertIsNone(self.store.get_hosted_provider_selection(workspace_id='workspace-a', profile='fast_model'))

    def test_saved_model_is_workspace_scoped_and_defaults_to_low(self):
        selected = self.configure()
        self.assertEqual(computer_actor_selection(self.store, 'workspace-a'), selected)
        self.assertEqual(selected.reasoning_effort, 'low')
        self.assertEqual(computer_actor_selection(self.store, 'workspace-b').model_id, 'gpt-6.1-sol')
        changed = self.configure(reasoning_effort='medium')
        self.assertEqual(changed.created_at, selected.created_at)

    def test_execution_mode_and_recovery_selection_are_persisted(self):
        selection = self.configure(model_id='gpt-6-luna', execution_mode='delegated',
            fallback_model_id='gpt-6.1-sol', fallback_reasoning_effort='medium')
        self.assertEqual(selection.fallback_model_id, 'gpt-6.1-sol')
        self.assertEqual(computer_actor_settings_payload(self.store, 'workspace-a')['execution_mode'], 'delegated')
        selection = self.configure(execution_mode='direct')
        self.assertEqual(selection.execution_mode, 'direct')
        self.assertIsNone(selection.fallback_model_id)

    def test_invalid_modes_and_recovery_models_do_not_overwrite_selection(self):
        saved = self.configure()
        for kwargs in [{'execution_mode': 'bad'}, {'fallback_model_id': 'text-only', 'fallback_reasoning_effort': 'medium'},
                       {'fallback_model_id': 'gpt-6-sol', 'fallback_reasoning_effort': 'medium'},
                       {'execution_mode': 'direct', 'fallback_model_id': 'gpt-6-luna', 'fallback_reasoning_effort': 'medium'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ProviderSelectionError):
                self.configure(**kwargs)
        self.assertEqual(computer_actor_selection(self.store, 'workspace-a'), saved)

    def test_unsupported_provider_model_and_effort_are_rejected_before_persistence(self):
        for values in ({'provider_id': 'jev'}, {'model_id': 'gpt-6-luna-decision'},
                       {'model_id': 'text-only'}, {'reasoning_effort': 'none'}):
            with self.subTest(values=values), self.assertRaises(ProviderSelectionError):
                self.configure(**values)
        self.assertIsNone(self.store.get_task_provider_selection(workspace_id='workspace-a', task_kind='computer_use'))

    def test_unavailable_saved_selection_is_reported_without_silent_fallback(self):
        selected = self.configure()
        self.adapter.model_options = lambda **_kwargs: []
        payload = computer_actor_settings_payload(self.store, 'workspace-a')
        self.assertEqual(payload['model_id'], selected.model_id)
        self.assertFalse(payload['available'])
        with self.assertRaises(ProviderSelectionError):
            validate_computer_actor_selection(selected)

    def test_catalog_excludes_text_only_models_and_factory_passes_selection(self):
        selected = self.configure()
        payload = computer_actor_settings_payload(self.store, 'workspace-a')
        self.assertEqual([m['model_id'] for m in payload['providers'][0]['models']], ['gpt-6-luna', 'gpt-6-sol', 'gpt-6.1-sol'])
        with patch('core.providers.computer_actor_factory.CodexComputerActor') as actor:
            create_computer_actor('session', 'binding', selection=selected)
            actor.assert_called_once_with('session', 'binding', selection=selected)

    def test_catalog_failure_does_not_offer_or_save_a_guessed_fallback(self):
        adapter = CodexProviderAdapter()
        with patch('core.providers.computer_actor_settings.CodexProviderAdapter', return_value=adapter), patch.object(
            adapter, '_runtime_command', return_value='review-catalog-unavailable'), patch(
            'core.providers.provider_codex_models.subprocess.run',
            side_effect=subprocess.TimeoutExpired('codex debug models', 5)):
            payload = computer_actor_settings_payload(self.store, 'workspace-a')
            self.assertEqual(payload['providers'][0]['models'], [])
            self.assertFalse(payload['available'])
            with self.assertRaises(ProviderSelectionError):
                self.configure(model_id='gpt-6.1-sol')
        self.assertIsNone(self.store.get_task_provider_selection(workspace_id='workspace-a', task_kind='computer_use'))

    def test_unknown_image_capability_is_not_admitted(self):
        self.adapter.model_options = lambda **_kwargs: [ProviderModelOption('unknown', 'Unknown', None, None)]
        payload = computer_actor_settings_payload(self.store, 'workspace-a')
        self.assertEqual(payload['providers'][0]['models'], [])

    def test_selection_survives_store_reconstruction_and_has_unique_control_plane_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = ControlStoreSettings.from_environment(repository_root=Path(directory), environment={})
            collections = build_control_plane_collections(settings)
            self.assertIn('provider_task_selections', [spec.name for spec in control_plane_collection_specs(collections)])
            self.store = ProviderDocumentStore(collections.provider)
            selected = self.configure()
            self.store = ProviderDocumentStore(build_control_plane_collections(settings).provider)
            self.assertEqual(computer_actor_selection(self.store, 'workspace-a'), selected)

    def api(self, method='GET', body=None, forbidden=False):
        state = SimpleNamespace(provider_store=self.store, workspace_store=object())
        context = RequestSession(SimpleNamespace(user_id='owner'), SimpleNamespace(session_id='auth'), 'workspace-a')
        response = {}
        raw = json.dumps(body).encode() if body is not None else b''
        environ = {'PATH_INFO': '/api/settings/computer-use', 'REQUEST_METHOD': method,
                   'wsgi.input': BytesIO(raw), 'CONTENT_LENGTH': str(len(raw))}
        with patch('core.api.settings_api.require_session', return_value=context), patch(
            'core.api.computer_actor_settings_api.require_provider_selection_authority',
            side_effect=AuthorizationError('provider_selection_forbidden') if forbidden else None):
            result = handle_settings_api(state, environ, lambda status, headers: response.update(status=status))
        return response['status'], json.loads(b''.join(result))

    def test_api_read_and_save_return_actual_selected_model(self):
        status, payload = self.api()
        self.assertEqual(status, '200 OK')
        self.assertEqual(payload['reasoning_effort'], 'medium')
        status, payload = self.api('POST', {'workspace_id': 'workspace-a', 'provider_id': 'codex',
            'model_id': 'gpt-6-sol', 'reasoning_effort': 'medium'})
        self.assertEqual(status, '200 OK')
        self.assertEqual((payload['model_id'], payload['reasoning_effort']), ('gpt-6-sol', 'medium'))

    def test_api_member_can_read_but_cannot_write(self):
        status, payload = self.api(forbidden=True)
        self.assertEqual(status, '200 OK')
        self.assertFalse(payload['can_configure'])
        status, _ = self.api('POST', {}, forbidden=True)
        self.assertEqual(status, '403 Forbidden')

    def test_api_rejects_cross_workspace_and_invalid_shapes(self):
        valid = {'workspace_id': 'workspace-a', 'provider_id': 'codex', 'model_id': 'gpt-6-luna'}
        for body in ({**valid, 'workspace_id': 'workspace-b'}, {**valid, 'model_id': ['bad']},
                     {**valid, 'reasoning_effort': 1}, {**valid, 'arbitrary': True}, {**valid, 'model_id': 'missing'}):
            with self.subTest(body=body):
                self.assertEqual(self.api('POST', body)[0], '400 Bad Request')
        self.assertEqual(self.api('DELETE')[0], '405 Method Not Allowed')
