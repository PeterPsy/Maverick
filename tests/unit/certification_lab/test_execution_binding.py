from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from core.certification_lab.execution_binding import build_lab_execution_binding
from core.providers.agentic_models import ActorSelectionPolicy, WorkspaceAgenticProfileBinding
from core.providers.certificate_service import validate_certificate_for_binding_with_revision_fence
from core.providers.certification_target import builtin_api_certification_profile
from core.runtime.authority import EffectiveRuntimeAuthority, effective_authority_audit_payload, effective_runtime_capability_payload
from core.runtime.execution_binding import canonical_digest, execution_binding_from_document, fork_runtime_execution_binding
from core.runtime.hosted_provider_runtime import HostedProviderRuntimeRegistry
from core.runtime.lifecycle_service_sessions import create_runtime_session
from core.runtime.remote_agentic_admission import require_remote_agentic_dispatch
from tests.support.lab_permits import installed_permit


class LabExecutionBindingTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store, _key, self.permit, self.ref = installed_permit(self.root)
        owner = self.store.claim(self.ref, session_id='one', scenario_id='nested-edit')
        profile = builtin_api_certification_profile('openrouter')
        now = datetime.now(UTC)
        workspace = WorkspaceAgenticProfileBinding(
            'lab-workspace-pin', self.permit.workspace.workspace_id, profile.definition_id, profile.revision,
            self.permit.credential_binding_id, True, False, ActorSelectionPolicy(False, (self.permit.workspace.actor_id,), (), ()),
            profile.policy_ceiling, profile.egress_policy_id, profile.egress_policy_revision, 1, now, now,
        )
        self.binding = build_lab_execution_binding(self.store, ownership=owner, definition=profile,
                                                   workspace_binding=workspace, reasoning_effort='medium')

    def test_exact_lab_pin_roundtrip_has_no_certificate_and_cannot_be_implicitly_forked(self):
        self.assertEqual(execution_binding_from_document(asdict(self.binding)), self.binding)
        self.assertIsNone(self.binding.capability_certificate_id)
        self.assertIsNone(self.binding.certificate_evidence_digest)
        self.assertEqual(self.binding.certified_reasoning_efforts, ())
        with self.assertRaisesRegex(ValueError, 'individually granted'):
            fork_runtime_execution_binding(self.binding, session_id='child', created_at=datetime.now(UTC))
        for field in ('authorization_domain', 'lab_permit_reference', 'lab_reasoning_efforts'):
            document = asdict(self.binding)
            document.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                execution_binding_from_document(document)

    def test_lab_pin_or_permit_is_rejected_in_production_before_any_store_write_or_dispatch(self):
        for target in (self.binding, self.permit):
            store = Mock()
            with self.subTest(target=type(target).__name__):
                with self.assertRaisesRegex(Exception, 'lab_authority_forbidden_in_production'):
                    create_runtime_session(store, session_id='one', workspace_id='synthetic', agent_id='chat', execution_binding=target)
                with self.assertRaisesRegex(Exception, 'lab_authority_forbidden_in_production'):
                    require_remote_agentic_dispatch(target)
                with self.assertRaisesRegex(Exception, 'lab_authority_forbidden_in_production'):
                    HostedProviderRuntimeRegistry().resolve(target)
                with self.assertRaisesRegex(Exception, 'lab_authority_forbidden_in_production'):
                    validate_certificate_for_binding_with_revision_fence(store, binding=target, adapter=object())
                self.assertEqual(store.mock_calls, [])

    def test_existing_production_digest_is_not_rewritten_but_cannot_supply_lab_authority(self):
        pin = replace(self.binding, authorization_domain='production', lab_permit_reference=None, lab_reasoning_efforts=(),
                      capability_certificate_id='missing-production-certificate', certificate_evidence_digest='d' * 64,
                      certified_reasoning_efforts=('medium',), binding_digest='')
        document = asdict(pin)
        for field in ('authorization_domain', 'lab_permit_reference', 'lab_reasoning_efforts'):
            document.pop(field)
        document['binding_digest'] = canonical_digest(document)
        loaded = execution_binding_from_document(document)
        self.assertEqual(loaded.authorization_domain, 'production')
        self.assertEqual(loaded.binding_digest, document['binding_digest'])
        self.assertIsNone(loaded.lab_permit_reference)
        changed = asdict(self.binding)
        changed['authorization_domain'] = 'production'
        with self.assertRaises(ValueError):
            execution_binding_from_document(changed)

    def test_experimental_snapshot_is_not_presented_as_active_certification(self):
        authority = EffectiveRuntimeAuthority(
            self.binding.execution_binding_id, 'turn', None, self.permit.capability_ceiling, (), 'full-access',
            self.permit.egress_policy_id, (), 'healthy', '', datetime.now(UTC),
            authorization_domain='certification_lab', lab_permit_reference=self.ref,
            lab_permit_expires_at=self.permit.expires_at, tcb_posture='experimental',
        )
        audit = effective_authority_audit_payload(authority)
        public = effective_runtime_capability_payload(authority)
        self.assertEqual(public['status'], 'experimental')
        self.assertNotIn('certificate', public)
        self.assertNotIn('certificate_id', audit)
        self.assertFalse(audit['lab_authorization']['certification_active'])
        self.assertNotIn('certified_upstream_ids', public['provider'])


if __name__ == '__main__':
    unittest.main()
