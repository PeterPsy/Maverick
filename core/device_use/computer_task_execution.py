"""One shared task budget, progress and replay fence across model handoffs."""

import time

from core.device_use.computer_actor_recovery import ComputerActorRecovery
from core.device_use.computer_task_progress import ComputerTaskProgress


def execute_computer_task(client, task, *, binding, invoke, active, usage_sink,
                          fallback_factory=None, timeout_seconds=180, max_steps=64):
    started = time.monotonic()
    deadline = started + timeout_seconds
    recovery = ComputerActorRecovery(binding.initial_app)
    progress = ComputerTaskProgress(task)
    attempts, steps, fallback_used, checkpoints = [], 0, False, 0
    jpeg = None
    output = {'status': 'needs_decision', 'summary': 'computer_actor_time_budget', 'evidence': '', 'steps': 0}
    fallback = None
    try:
        if client.model_id == 'gpt-6-luna' and client.reasoning_effort == 'low' and not progress.steps:
            output = {'status': 'needs_decision', 'summary': 'computer_actor_plan_required', 'evidence':
                'No input sent. Supply exact structured steps and expected effects, or use the configured recovery model.', 'steps': 0}
            attempts.append({'model_id': client.model_id, 'reasoning_effort': client.reasoning_effort,
                'status': output['status'], 'reason': output['summary'], 'steps': 0, 'elapsed_ms': 0})
            if fallback_factory and active() and time.monotonic() < deadline:
                # No inference or input has run: a pre-input route cannot replay
                # a mutation. Broad navigation remains with the capable model.
                fallback_used = True
                fallback = client = fallback_factory()
            else:
                return {**output, 'attempts': attempts, 'fallback_used': False,
                        'verified_steps': 0, 'task_elapsed_ms': round((time.monotonic() - started) * 1000, 3)}, None
        while active() and time.monotonic() < deadline and steps < max_steps:
            attempt_started = time.monotonic()
            output, jpeg = client.run(task, invoke=invoke, active=active, usage_sink=usage_sink,
                recovery=recovery, progress=progress, timeout_seconds=max(0.01, deadline - time.monotonic()),
                max_steps=max_steps - steps)
            used = output.get('steps', 0)
            steps += used
            attempts.append({'model_id': client.model_id, 'reasoning_effort': client.reasoning_effort,
                'status': output['status'], 'reason': output['summary'], 'steps': used,
                'elapsed_ms': round((time.monotonic() - attempt_started) * 1000, 3)})
            if output['status'] == 'completed':
                break
            if output['summary'] == 'computer_actor_context_checkpoint' and checkpoints < 7:
                checkpoints += 1
                continue
            # Escalate only at a verified structured-step boundary. A new model
            # must never restart a goal after an input with an unknown effect.
            safe_boundary = bool(progress.steps and progress.pending is None
                                 and recovery.pending is None and progress.observation is not None)
            eligible = output['summary'] in {'computer_actor_criterion_not_met',
                'computer_actor_completion_unverified', 'computer_actor_invalid_result',
                'computer_actor_step_mismatch', 'computer_actor_step_budget'}
            eligible = eligible or (output['status'] in {'needs_decision', 'blocked'}
                and not output['summary'].startswith('computer_actor_'))
            if (not fallback_used and fallback_factory and safe_boundary and eligible and active()
                and steps < max_steps and time.monotonic() < deadline):
                fallback_used = True
                fallback = client = fallback_factory()
                continue
            break
        output = {**output, 'steps': steps, 'attempts': attempts, 'fallback_used': fallback_used,
                  'verified_steps': progress.index, 'task_elapsed_ms': round((time.monotonic() - started) * 1000, 3)}
        return output, jpeg
    finally:
        if fallback is not None:
            fallback.close()
