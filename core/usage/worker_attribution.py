"""Trusted internal worker streams aggregated under their owning conversation."""

from dataclasses import replace


def attributed_worker_session(session, payload):
    if (payload.get("usage_worker") != "computer_actor"
        or payload.get("provider_id") != "codex"
        or payload.get("model_id") != "gpt-6-luna"
        or not str(payload.get("source", "")).startswith("codex_computer_actor:")):
        return session
    return replace(session, session_id=session.session_id + ":computer_actor")


def owned_usage_session_ids(session_ids):
    owners = {session_id: session_id for session_id in session_ids}
    owners.update({session_id + ":computer_actor": session_id for session_id in session_ids})
    return owners
