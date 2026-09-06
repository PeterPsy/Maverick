"""Offline human peer uses the actual confirmation API, never an authority patch."""

import asyncio
from types import SimpleNamespace

from core.api.runtime_tool_confirmation_api import handle_runtime_tool_confirmation


async def execute_with_operator(worker, peer):
    state = worker.state
    context = SimpleNamespace(user=state.identity_store.get_user('lab-operator'),
                              workspace_id=worker.session.workspace_id)
    task = asyncio.create_task(worker.execute(
        turn_id='lab-turn-one',
        task='Read all applicable instructions, fix exercise/value.py so the test passes, run the test and give a final.',
    ))
    approved = set()
    try:
        while not task.done():
            await asyncio.sleep(0.05)
            for item in state.runtime_store.list_tool_invocations(session_id=worker.session.session_id):
                if item.state != 'awaiting_confirmation' or item.invocation_id in approved:
                    continue
                # The offline operator approves ONLY the exact two anticipated
                # effects. This is not installed in the natural/live worker.
                assert item.resolved_tool_handle in {'core-capability:filesystem.edit', 'core-capability:shell.run'}
                assert state.runtime_tool_ledger.load_arguments(item) == peer.arguments[item.provider_tool_call_id]
                statuses = []
                response = handle_runtime_tool_confirmation(
                    state, context, turn_id=item.turn_id, invocation_id=item.invocation_id, method='POST',
                    body={'decision': 'approve', 'arguments_digest': item.arguments_digest,
                          'expected_invocation_revision': item.revision},
                    start_response=lambda status, _headers: statuses.append(status),
                )
                assert statuses == ['200 OK'], response
                approved.add(item.invocation_id)
                worker.lab.evidence.record('operator_confirmation_response', {'response': response, 'actor_id': context.user.user_id})
        result = await task
        assert approved, 'The mutation bypassed the real confirmation policy'
        return result
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
