"""Actual mutable-store negative checks in the private vertical installation."""

from dataclasses import replace

from core.providers.errors import CapabilityCertificateError
from core.runtime.authority_service import resolve_runtime_authority_snapshot, revalidate_runtime_authority_snapshot
from core.runtime.execution_binding import canonical_digest


def expect_denied(call, reason=None):
    try:
        call()
    except (ValueError, CapabilityCertificateError) as error:
        if reason:
            assert reason in str(error), (reason, error)
    else:
        raise AssertionError('Experimental identity change was accepted')


def verify_private_fences(state, session, adapter):
    lab = state.lab_runtime_authorization
    # A correctly re-digested object is still not the owned immutable pin.
    for field, value in (
        ('workspace_id', 'different'), ('reasoning_effort', 'high'),
        ('model_id', 'different'), ('adapter_artifact_digest', '0' * 64),
        ('tcb_live_digest', '1' * 64), ('credential_binding_id', 'different'),
        ('egress_policy_revision', 'different'),
    ):
        def changed_binding():
            binding = replace(session.execution_binding, **{field: value}, binding_digest='')
            binding = replace(binding, binding_digest=canonical_digest(binding))
            lab.validate_binding(binding)
        expect_denied(changed_binding)
    for field, value in (
        ('owner_user_id', 'lab-operator'), ('workspace_id', 'different'),
        ('workspace_root', session.workspace_root + '-different'),
        ('workdir', '/'), ('runtime_root', '/'), ('lab_installation_id', 'different'),
    ):
        expect_denied(lambda: lab.validate_session(replace(session, **{field: value})))
    authority = resolve_runtime_authority_snapshot(state, session=session, adapter=adapter, turn_id='offline-fence')
    actor = state.identity_store.get_user(session.owner_user_id)
    try:
        state.identity_store.save_user(replace(actor, platform_role='admin'))
        expect_denied(lambda: revalidate_runtime_authority_snapshot(
            state, session=session, adapter=adapter, authority=authority,
        ), 'runtime_actor_policy_denied')
    finally:
        state.identity_store.save_user(actor)
    # Changing source bytes, even with the same Git HEAD, invalidates the live
    # TCB. This only mutates/restores the disposable frozen test installation.
    source = lab.repository_root / 'core/certification_lab/worker.py'
    original = source.read_bytes()
    try:
        source.write_bytes(original + b'\n# offline drift\n')
        expect_denied(lambda: lab.validate_candidate(adapter), 'lab_candidate_drift')
    finally:
        source.write_bytes(original)
    # An independent process cannot reclaim this named session on restart.
    from core.certification_lab.permit_store import LabPermitStore

    reopened = LabPermitStore(lab.permit_store.path, trust=lab.permit_store.trust)
    expect_denied(lambda: reopened.claim(lab.ownership.reference, session_id=session.session_id,
                                         scenario_id=lab.ownership.scenario_id), 'lab_session_already_claimed')
