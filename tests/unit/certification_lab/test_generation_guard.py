"""The job fence must use the shared request guard, never a lab-only shortcut."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.certification_lab.generation_budget import LabGenerationAuthorization
from core.providers.agentic_protocol import EphemeralCredential
from core.runtime.hosted_agentic_transport import (
    HostedTransportAuthorization, bind_hosted_generation_revalidator, revalidate_hosted_generation,
)


class LabGenerationGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_guard_is_task_local_and_never_leaks_out_of_a_generation(self):
        arrived = 0
        ready = asyncio.Event()

        async def generation(name):
            nonlocal arrived
            value = HostedTransportAuthorization(name, None)
            with bind_hosted_generation_revalidator(lambda: value):
                arrived += 1
                if arrived == 2:
                    ready.set()
                await ready.wait()
                self.assertIs(revalidate_hosted_generation(), value)
            with self.assertRaisesRegex(Exception, 'hosted_generation_guard_missing'):
                revalidate_hosted_generation()

        await asyncio.gather(generation('one'), generation('two'))
        with self.assertRaisesRegex(Exception, 'hosted_generation_guard_missing'):
            revalidate_hosted_generation()

    async def test_missing_guard_invalid_guard_and_rotated_credential_fail_closed(self):
        lab = Mock()
        authorization = LabGenerationAuthorization(object(), lab)
        credential = EphemeralCredential('synthetic-old')
        with self.assertRaisesRegex(Exception, 'hosted_generation_guard_missing'):
            authorization.revalidate(credential)
        with bind_hosted_generation_revalidator(lambda: None):
            with self.assertRaisesRegex(Exception, 'hosted_generation_guard_invalid'):
                authorization.revalidate(credential)
        fresh = HostedTransportAuthorization(SimpleNamespace(session=object()), EphemeralCredential('synthetic-new'))
        with bind_hosted_generation_revalidator(lambda: fresh):
            with self.assertRaisesRegex(Exception, 'lab_credential_changed'):
                authorization.revalidate(credential)

    async def test_every_revalidation_calls_the_actual_mutable_guard_and_current_session(self):
        lab = Mock()
        authorization = LabGenerationAuthorization(object(), lab)
        credential = EphemeralCredential('synthetic')
        fresh = HostedTransportAuthorization(SimpleNamespace(session=object()), credential)
        guard = Mock(return_value=fresh)
        with bind_hosted_generation_revalidator(guard):
            authorization.revalidate(credential)
            guard.side_effect = RuntimeError('actor_or_tcb_revoked_during_pacing')
            with self.assertRaisesRegex(RuntimeError, 'revoked_during_pacing'):
                authorization.revalidate(credential)
        self.assertEqual(guard.call_count, 2)
        lab.validate_session.assert_called_once_with(fresh.context.session)
