"""Ephemeral operator ownership and cancellation by the original Mac lease."""

import threading

from core.device_use.errors import DeviceUseUnavailableError


_ACTORS = {}
_LOCK = threading.Lock()


def register_computer_actor(state, session_id, activation_id):
    from core.device_use.computer_actor import ComputerInteraction

    with _LOCK:
        previous = _ACTORS.pop(session_id, None)
        _ACTORS[session_id] = ComputerInteraction(state, session_id, activation_id)
    if previous is not None:
        previous.cancel(close=True)


def invoke_computer_actor(session_id, **kwargs):
    with _LOCK:
        actor = _ACTORS.get(session_id)
    if actor is None:
        raise DeviceUseUnavailableError("computer_actor_unavailable")
    return actor.run(**kwargs)


def cancel_computer_actor(session_id, *, activation_id=None, forget=False, close=False):
    with _LOCK:
        actor = _ACTORS.get(session_id)
        if actor is None or (activation_id is not None and actor.activation_id != activation_id):
            return
        if forget:
            _ACTORS.pop(session_id, None)
    actor.cancel(close=forget or close)


def cancel_activation_computer_actors(activation_id):
    with _LOCK:
        actors = [actor for actor in _ACTORS.values() if actor.activation_id == activation_id]
    for actor in actors:
        actor.cancel(close=True)
