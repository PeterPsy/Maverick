"""Trusted internal worker streams aggregated under their owning conversation."""

from dataclasses import replace


def attributed_worker_session(session, payload):
    provider_id = str(payload.get("provider_id") or "")
    if (payload.get("usage_worker") != "computer_actor"
        or not provider_id or not payload.get("model_id")
        or not str(payload.get("source", "")).startswith("computer_actor:" + provider_id + ":")):
        return session
    return replace(session, session_id=session.session_id + ":computer_actor")


def owned_usage_session_ids(session_ids):
    owners = {session_id: session_id for session_id in session_ids}
    owners.update({session_id + ":computer_actor": session_id for session_id in session_ids})
    return owners
