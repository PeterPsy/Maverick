"""Run inside a frozen independent source copy. Only the HTTP peer is simulated."""

import asyncio
import base64
from dataclasses import fields
from datetime import UTC, datetime, timedelta
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from core.certification_lab.bootstrap import bootstrap_lab_worker, lab_process_environment
from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.isolation import LabInstallationLayout, directory_identity
from core.certification_lab.permit import (
    LabApiTarget, LabBudgetScope, LabCandidateIdentity, LabExecutionPermit, LabSessionGrant, LabWorkspaceScope,
)
from core.certification_lab.permit_codec import sign_lab_permit
from core.certification_lab.permit_store import LabPermitStore
from core.certification_lab.seed import seed_lab_installation
from core.certification_lab.trust import LabPermitTrust
from core.certification_lab.worker import LabWorker
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_budget_ledger import CertificationBudgetLedger, CertificationBudgetLimit
from core.providers.certification_target import api_profile_target_digest
from core.providers.certified_execution_tcb import certified_tcb_identity
from core.runtime.hosted_agentic_factory import build_hosted_agentic_engine_adapter
from core.runtime.tool_schema import provider_tool_name
from tests.unit.providers.test_openrouter_agentic_catalog import _model_catalog, _zdr_catalog
from tests.unit.providers.test_openrouter_agentic_codec import _text_stream, _tool_stream
from tests.support.lab_offline_operator import execute_with_operator
from tests.support.lab_offline_fences import verify_private_fences


class Response(io.BytesIO):
    def __init__(self, content, url, content_type):
        super().__init__(content)
        self.url = url
        self.headers = {'Content-Type': content_type}

    def geturl(self):
        return self.url


class OfflinePeer:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.instructions = None
        self.read = None
        self.arguments = {}

    def open(self, request):
        url = request.full_url
        if request.get_method() == 'GET':
            self.gets.append(url)
            if url.endswith('/endpoints/zdr'):
                body = _zdr_catalog()
            elif url.endswith('/models/deepseek/deepseek-v4-flash/endpoints'):
                body = _model_catalog()
            else:
                raise AssertionError('Unexpected catalog URL: ' + url)
            return Response(json.dumps(body).encode(), url, 'application/json')
        assert url == 'https://openrouter.ai/api/v1/chat/completions'
        payload = json.loads(request.data)
        assert not any(any(forbidden in tool['function']['name'] for forbidden in
                           ('permit', 'trust', 'certific', 'secret', 'publisher', 'reviewer'))
                       for tool in payload.get('tools', [])), 'Operator authority exposed to model tools'
        self.posts.append(payload)
        ordinal = len(self.posts)
        results = [json.loads(item['content']) for item in payload['messages'] if item['role'] == 'tool']
        if ordinal == 1:
            handle, arguments = 'workspace.instructions', {'path': 'exercise/value.py'}
        elif ordinal == 2:
            self.instructions = results[-1]
            handle, arguments = 'filesystem.read', {'path': 'exercise/value.py'}
        elif ordinal == 3:
            self.read = results[-1]
            handle, arguments = 'filesystem.edit', {
                'path': 'exercise/value.py', 'old_text': 'return 1', 'new_text': 'return 2',
                'expected_resource_identity': self.read['resource_identity'],
                'expected_resource_revision': self.read['resource_revision'],
                'instruction_scope_digest': self.instructions['scope_digest'],
            }
        elif ordinal == 4:
            handle, arguments = 'shell.run', {
                'argv': ['python3', '-B', '-m', 'unittest', 'discover', '-s', 'exercise', '-p', 'test_*.py'],
                'mutation_scopes': [],
            }
        else:
            assert ordinal == 5, 'Unexpected extra generation'
            assert results[-1]['exit_code'] == 0, results[-1]
            stream = _text_stream(f'lab-generation-{ordinal}', 'Fixed value and ran the test successfully.')
            return self.response(stream, url)
        name = provider_tool_name('core-capability:' + handle)
        assert any(tool['function']['name'] == name for tool in payload['tools']), handle
        self.arguments[f'lab-call-{ordinal}'] = arguments
        stream = _tool_stream(f'lab-generation-{ordinal}', name, call_id=f'lab-call-{ordinal}', arguments=arguments)
        return self.response(stream, url)

    @staticmethod
    def response(stream, url):
        content = ''.join('data: ' + json.dumps(event) + '\n\n' for event in stream) + 'data: [DONE]\n\n'
        return Response(content.encode(), url, 'text/event-stream')


def run(config):
    layout = LabInstallationLayout(
        config['installation_id'], Path(config['source']), Path(config['workspace']),
        Path(config['control']), Path(config['vault']), Path(config['operator']),
        tuple(map(Path, config['active_roots'])), config['source_commit'],
    )
    # Importing tests installs generic test defaults. Discard them completely
    # before lab bootstrap; the real strict environment check remains intact.
    os.environ.clear()
    os.environ.update(lab_process_environment(layout))
    vault_key = layout.vault_root / 'key'
    vault_key.write_bytes(b'z' * 32)
    os.chmod(vault_key, 0o600)
    state, publication, credential, workspace_binding, attestation = seed_lab_installation(
        layout, vault_key_path=vault_key, actor_id='lab-member', operator_id='lab-operator',
        provider_id='openrouter', credential_binding_id='lab-provider-binding', credential_value='offline-not-a-provider-key',
    )
    root = layout.workspace_root
    (root / 'AGENTS.md').write_text('Use the nested instructions and retain function signatures.\n')
    (root / 'exercise').mkdir()
    (root / 'exercise/AGENTS.md').write_text('Change only value.py. Run test_value.py before the final.\n')
    (root / 'exercise/value.py').write_text('def value():\n    return 1\n')
    (root / 'exercise/test_value.py').write_text('import unittest\nfrom value import value\nclass Check(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value(), 2)\n')
    # The test operator, not the worker, authorizes an experiment. No capability
    # evidence or certificate is produced/inserted anywhere in this fixture.
    key = Ed25519PrivateKey.generate()
    trust_path = layout.operator_root / 'trust.json'
    trust_path.write_text(json.dumps({'schema': 'maverick-lab-issuer-trust.v1', 'installation_id': layout.installation_id,
        'issuers': {'offline-issuer': {'public_key': base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
                                      'operator_authorization_refs': ['a' * 64]}}}))
    trust_path.chmod(0o600)
    permits = LabPermitStore.create(layout.operator_root / 'permits.sqlite', trust=LabPermitTrust(trust_path, layout.installation_id))
    ledger = CertificationBudgetLedger.create(layout.operator_root / 'budget.sqlite', authorization_ref='a' * 64,
                                               limits=(CertificationBudgetLimit('openrouter', 'paid', 4_500_000, 200, 0),))
    production_adapter = build_hosted_agentic_engine_adapter(state, provider_registry=state.provider_registry,
                                                            onboarding_catalog=state.maverick_agent_onboarding_catalog)
    artifact = runtime_adapter_artifact_digest(production_adapter)
    tcb = certified_tcb_identity()
    now = datetime.now(UTC)
    profile = publication.profile
    permit = LabExecutionPermit(
        'offline-permit', 'offline-job', layout.installation_id, 'offline-issuer', 'a' * 64,
        LabApiTarget(profile.definition_id, profile.revision, api_profile_target_digest(profile), 'openrouter', publication.provider_config.endpoint_url),
        LabCandidateIdentity(layout.source_commit, profile.adapter_id, production_adapter.adapter_version, artifact,
                             tcb.manifest_id, tcb.manifest_version, tcb.structure_digest, tcb.live_digest),
        LabWorkspaceScope(root.name, str(root), directory_identity(root), attestation.attestation_id, attestation.revision,
                          'lab-member', (LabSessionGrant('lab-one', 'nested-edit-test'),)),
        ('medium',), RuntimeCapabilitySet(**{f.name: ('file',) if f.name == 'attachment_modalities' else True for f in fields(RuntimeCapabilitySet)}),
        profile.policy_ceiling, profile.routing_constraint, profile.egress_policy_id, profile.egress_policy_revision,
        credential.binding_id, __import__('core.runtime.execution_binding', fromlist=['canonical_digest']).canonical_digest(credential),
        LabBudgetScope(ledger.identity_digest, ledger.policy_digest, publication.provider_config.token_cost_policy.digest, 4_500_000, 200),
        1, now, now + timedelta(minutes=10),
    )
    reference = permits.install(sign_lab_permit(permit, private_key=key))
    del key
    state, session, adapter = bootstrap_lab_worker(
        layout, vault_key_path=vault_key, permit_store=permits, reference=reference, ledger=ledger,
        session_id='lab-one', scenario_id='nested-edit-test', workspace_binding_id=workspace_binding.binding_id, reasoning_effort='medium',
    )
    assert runtime_adapter_artifact_digest(adapter) == artifact, 'Lab and production composed different adapter artifacts'
    assert not state.provider_store.list_capability_certificates()
    verify_private_fences(state, session, adapter)
    peer = OfflinePeer()
    with patch('socket.socket.connect', side_effect=AssertionError('Live network forbidden')) as network, patch(
        'urllib.request.OpenerDirector.open', new=lambda _opener, request, *a, **kw: peer.open(request),
    ):
        worker = LabWorker(state=state, session=session, adapter=adapter)
        observed = asyncio.run(execute_with_operator(worker, peer))
        assert observed.result.exit_code == 0, repr(observed.result)
        assert 'return 2' in (root / 'exercise/value.py').read_text()
        assert len(peer.posts) == 5, len(peer.posts)
        count = (len(peer.posts), len(peer.gets))
        permits.revoke(reference.permit_id, expected_revision=1)
        try:
            asyncio.run(worker.execute(turn_id='lab-turn-two', task='Continue.'))
            raise AssertionError('Revoked permit executed another turn')
        except LabAuthorizationError as error:
            assert error.reason_code == 'lab_permit_revoked'
        assert count == (len(peer.posts), len(peer.gets))
        network.assert_not_called()
    return {'generations': len(peer.posts), 'artifacts': len(observed.observation_refs),
            'certificate_count': len(state.provider_store.list_capability_certificates()),
            'remaining_processes': adapter.process_registry.live_process_count(session_id=session.session_id),
            'authority_domain': session.authorization_domain}


if __name__ == '__main__':
    sys.excepthook = sys.__excepthook__
    # Cover bootstrap and all negative/preparation checks too, not only the
    # generation peer below. No test installation can accidentally reach HTTPS.
    with patch('socket.socket.connect', side_effect=AssertionError('Live network forbidden')) as network:
        result = run(json.loads(Path(sys.argv[1]).read_text()))
        network.assert_not_called()
    print(json.dumps(result))
