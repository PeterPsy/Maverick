"""Actor continuity for app-owned work deferred to trusted background hooks."""

from core.authorization.errors import AuthorizationError


def runtime_request_actor(request, actor_user_id):
    delegated = request.get("on_behalf_of_user_id", "")
    if not isinstance(delegated, str) or len(delegated) > 128:
        raise AuthorizationError("invalid_deferred_runtime_actor")
    delegated = delegated.strip()
    if delegated and actor_user_id and delegated != actor_user_id:
        raise AuthorizationError("deferred_runtime_actor_mismatch")
    # This field is accepted only from a trusted app result envelope. The normal
    # actor/profile and remote-admission gates still run for the recorded user.
    return actor_user_id or delegated or None
