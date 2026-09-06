"""Trusted bootstrap selection; never infer experimental authority from a pin."""

from core.certification_lab.authority import LabRuntimeAuthorization
from core.certification_lab.errors import LabAuthorizationError
from core.runtime.authorization_domain import require_production_authorization


def lab_authorization_for_state(state, binding):
    authority = getattr(state, 'lab_runtime_authorization', None)
    if authority is None:
        require_production_authorization(binding)
        return None
    if type(authority) is not LabRuntimeAuthorization:
        raise LabAuthorizationError('lab_trusted_context_invalid')
    if any(getattr(authority, name) is not getattr(state, name) for name in
           ('workspace_store', 'provider_store', 'runtime_store')):
        raise LabAuthorizationError('lab_trusted_context_invalid')
    authority.validate_binding(binding)
    return authority
