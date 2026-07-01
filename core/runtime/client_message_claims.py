"""Runtime client-message idempotency claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


CLIENT_MESSAGE_CLAIM_LEASE_SECONDS = 300.0


@dataclass(frozen=True)
class RuntimeClientMessageClaim:
    """Workspace-scoped reservation for one client-submitted chat message."""

    workspace_id: str
    client_message_id: str
    session_id: str
    turn_id: str
    created_at: datetime
    updated_at: datetime
    status: str = "claimed"
    lease_expires_at: datetime | None = None
