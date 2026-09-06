import base64
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.permit import LabNativeTarget, LabSessionGrant
from core.certification_lab.permit_codec import decode_permit, permit_bytes, sign_lab_permit
from core.certification_lab.permit_store import LabPermitStore
from core.certification_lab.trust import LabPermitTrust
from tests.support.lab_permits import installed_permit


class LabPermitStoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store, self.key, self.permit, self.ref = installed_permit(self.root)

    def test_roundtrip_no_certificate_fields_and_fresh_resolution(self):
        self.assertEqual(decode_permit(permit_bytes(self.permit)), self.permit)
        self.assertNotIn(b'certificate', permit_bytes(self.permit))
        self.assertEqual(self.store.resolve(self.ref), self.permit)
        self.assertEqual(LabPermitStore(self.store.path, trust=self.store.trust).resolve(self.ref), self.permit)

    def test_tamper_expired_revoked_untrusted_or_unavailable_fail(self):
        with self.assertRaisesRegex(LabAuthorizationError, 'signature_invalid'):
            self.store.install(sign_lab_permit(replace(self.permit, permit_id='wrong-key'), private_key=Ed25519PrivateKey.generate()))
        with self.assertRaisesRegex(LabAuthorizationError, 'expired'):
            self.store.resolve(self.ref, now=self.permit.expires_at)
        with self.assertRaisesRegex(LabAuthorizationError, 'expired'):
            self.store.resolve(self.ref, now=self.permit.issued_at - timedelta(seconds=1))
        with closing(sqlite3.connect(self.store.path)) as connection:
            document = permit_bytes(replace(self.permit, workspace=replace(self.permit.workspace, actor_id='attacker')))
            connection.execute('UPDATE permits SET document=?', (document,))
            connection.commit()
        with self.assertRaisesRegex(LabAuthorizationError, 'signature_invalid'):
            self.store.resolve(self.ref)
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.execute('UPDATE permits SET document=?', (permit_bytes(self.permit),))
            connection.commit()
        policy = json.loads(self.store.trust.path.read_text())
        policy['issuers']['offline-issuer']['public_key'] = base64.b64encode(b'x' * 32).decode()
        self.store.trust.path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(LabAuthorizationError, 'signature_invalid'):
            self.store.resolve(self.ref)
        self.store.trust.path.unlink()
        with self.assertRaises(LabAuthorizationError):
            self.store.resolve(self.ref)

    def test_cross_process_revocation_is_seen_and_cannot_be_renewed(self):
        code = '''from pathlib import Path
from core.certification_lab.permit_store import LabPermitStore
from core.certification_lab.trust import LabPermitTrust
import sys
s=LabPermitStore(Path(sys.argv[1]),trust=LabPermitTrust(Path(sys.argv[2]),'offline-lab'))
s.revoke('offline-permit',expected_revision=1)
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.store.path), str(self.store.trust.path)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        with self.assertRaisesRegex(LabAuthorizationError, 'revoked'):
            self.store.resolve(self.ref)
        with self.assertRaisesRegex(LabAuthorizationError, 'cas_conflict'):
            self.store.revoke('offline-permit', expected_revision=1)
        with self.assertRaisesRegex(LabAuthorizationError, 'already_exists'):
            self.store.install(sign_lab_permit(self.permit, private_key=self.key))

    def test_reference_cannot_cross_installation_job_or_revision(self):
        for changes in ({'installation_id': 'prod'}, {'job_id': 'other'}, {'permit_digest': 'f' * 64},
                        {'status_revision': 2}, {'permit_id': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(LabAuthorizationError):
                self.store.resolve(replace(self.ref, **changes))
        with self.assertRaisesRegex(LabAuthorizationError, 'installation_mismatch'):
            LabPermitStore(self.store.path, trust=LabPermitTrust(self.store.trust.path, 'other'))

    def test_ownership_and_binding_are_persistent_and_never_auto_renewed(self):
        owner = self.store.claim(self.ref, session_id='one', scenario_id='nested-edit')
        self.assertNotIn(owner.token, repr(owner))
        self.store.bind(owner, binding_digest='d' * 64)
        restarted = LabPermitStore(self.store.path, trust=self.store.trust)
        with self.assertRaisesRegex(LabAuthorizationError, 'already_claimed'):
            restarted.claim(self.ref, session_id='one', scenario_id='nested-edit')
        with self.assertRaisesRegex(LabAuthorizationError, 'already_pinned'):
            restarted.bind(owner, binding_digest='d' * 64)
        self.assertEqual(restarted.validate_ownership(owner, binding_digest='d' * 64), self.permit)
        with self.assertRaisesRegex(LabAuthorizationError, 'identity_mismatch'):
            restarted.validate_ownership(owner, binding_digest='e' * 64)
        with self.assertRaisesRegex(LabAuthorizationError, 'ownership_lost'):
            restarted.validate_ownership(replace(owner, token='a' * 64), binding_digest='d' * 64)
        restarted.complete(owner)
        with self.assertRaisesRegex(LabAuthorizationError, 'already_claimed'):
            restarted.claim(self.ref, session_id='one', scenario_id='nested-edit')

    def test_sessions_and_concurrency_exactly_granted(self):
        with self.assertRaisesRegex(LabAuthorizationError, 'not_granted'):
            self.store.claim(self.ref, session_id='one', scenario_id='invented')
        workspace = replace(self.permit.workspace, sessions=(LabSessionGrant('two', 'a'), LabSessionGrant('three', 'b')))
        permit = replace(self.permit, permit_id='second', workspace=workspace)
        ref = self.store.install(sign_lab_permit(permit, private_key=self.key))
        self.store.claim(ref, session_id='two', scenario_id='a')
        with self.assertRaisesRegex(LabAuthorizationError, 'concurrency_exceeded'):
            self.store.claim(ref, session_id='three', scenario_id='b')

    def test_domain_target_budgets_and_canonical_schema_cannot_be_confused(self):
        for changes in ({'purpose': 'production'}, {'max_concurrent_sessions': 2},
                        {'budget': replace(self.permit.budget, max_cost_microusd=4_500_001)},
                        {'expires_at': datetime.now(UTC) + timedelta(days=2)},
                        {'target': replace(self.permit.target, scope='native_connection')},
                        {'target': replace(self.permit.target, model_provider_id='google')},
                        {'workspace': replace(self.permit.workspace, sessions=(LabSessionGrant('one', 'a', 'one'),))}):
            with self.subTest(changes=changes), self.assertRaises(LabAuthorizationError):
                permit_bytes(replace(self.permit, **changes))
        native = LabNativeTarget('gemini-cli', 'google', 'native-connection', *(['d' * 64] * 4))
        permit = replace(self.permit, target=native, budget=replace(self.permit.budget, max_cost_microusd=0, max_requests=80))
        self.assertEqual(decode_permit(permit_bytes(permit)).target, native)
        with self.assertRaises(LabAuthorizationError):
            permit_bytes(replace(permit, budget=replace(permit.budget, max_cost_microusd=1)))
        raw = permit_bytes(self.permit)
        with self.assertRaises(LabAuthorizationError):
            decode_permit(raw.replace(b'"purpose":"certification_lab",', b''))
        with self.assertRaises(LabAuthorizationError):
            decode_permit(raw.replace(b'"purpose":', b'"purpose":"production","purpose":'))

    def test_store_missing_corrupt_or_symlink_denies(self):
        alias = self.root / 'alias.sqlite'
        alias.symlink_to(self.store.path)
        with self.assertRaises(LabAuthorizationError):
            LabPermitStore(alias, trust=self.store.trust)
        self.store.path.unlink()
        with self.assertRaises(LabAuthorizationError):
            self.store.resolve(self.ref)
        self.assertFalse(self.store.path.exists())


if __name__ == '__main__':
    unittest.main()
