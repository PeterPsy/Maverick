"""Document storage helpers for identity-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.identity.errors import SessionNotFoundError, UserNotFoundError
from core.identity.models import AuthSessionRecord, PasswordCredentialRecord, UserRecord


class DocumentCollection(Protocol):
    """Minimal collection protocol used by the control-plane stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


class IdentityStore(Protocol):
    """Persistence contract for identity-domain records."""

    def save_user(self, record: UserRecord) -> UserRecord:
        ...

    def get_user(self, user_id: str) -> UserRecord:
        ...

    def get_user_by_username(self, username: str) -> UserRecord:
        ...

    def list_users(self) -> list[UserRecord]:
        ...

    def delete_user(self, user_id: str) -> None:
        ...

    def save_password_credential(self, record: PasswordCredentialRecord) -> PasswordCredentialRecord:
        ...

    def get_password_credential(self, user_id: str) -> PasswordCredentialRecord:
        ...

    def delete_password_credential(self, user_id: str) -> None:
        ...

    def save_auth_session(self, record: AuthSessionRecord) -> AuthSessionRecord:
        ...

    def get_auth_session(self, session_id: str) -> AuthSessionRecord:
        ...

    def delete_auth_sessions_for_user(self, user_id: str) -> None:
        ...

    def revoke_auth_sessions_for_user(self, user_id: str, *, now) -> None:
        ...


@dataclass(frozen=True)
class IdentityCollections:
    """Collection bundle for identity persistence."""

    users: DocumentCollection
    credentials: DocumentCollection
    auth_sessions: DocumentCollection


class IdentityDocumentStore:
    """Persist identity-domain records in document collections."""

    def __init__(self, collections: IdentityCollections) -> None:
        self.collections = collections

    def save_user(self, record: UserRecord) -> UserRecord:
        payload = asdict(record)
        self.collections.users.update_one({"user_id": record.user_id}, {"$set": payload}, upsert=True)
        return record

    def get_user(self, user_id: str) -> UserRecord:
        document = self.collections.users.find_one({"user_id": user_id})
        if document is None:
            raise UserNotFoundError(f"User `{user_id}` was not found.")
        return UserRecord(**document)

    def get_user_by_username(self, username: str) -> UserRecord:
        document = self.collections.users.find_one({"username": username})
        if document is None:
            raise UserNotFoundError(f"User `{username}` was not found.")
        return UserRecord(**document)

    def list_users(self) -> list[UserRecord]:
        return [UserRecord(**document) for document in self.collections.users.find({})]

    def delete_user(self, user_id: str) -> None:
        self.collections.users.delete_one({"user_id": user_id})

    def save_password_credential(self, record: PasswordCredentialRecord) -> PasswordCredentialRecord:
        payload = asdict(record)
        self.collections.credentials.update_one({"user_id": record.user_id}, {"$set": payload}, upsert=True)
        return record

    def get_password_credential(self, user_id: str) -> PasswordCredentialRecord:
        document = self.collections.credentials.find_one({"user_id": user_id})
        if document is None:
            raise UserNotFoundError(f"No password credential exists for user `{user_id}`.")
        return PasswordCredentialRecord(**document)

    def delete_password_credential(self, user_id: str) -> None:
        self.collections.credentials.delete_one({"user_id": user_id})

    def save_auth_session(self, record: AuthSessionRecord) -> AuthSessionRecord:
        payload = asdict(record)
        self.collections.auth_sessions.update_one({"session_id": record.session_id}, {"$set": payload}, upsert=True)
        return record

    def get_auth_session(self, session_id: str) -> AuthSessionRecord:
        document = self.collections.auth_sessions.find_one({"session_id": session_id})
        if document is None:
            raise SessionNotFoundError(f"Auth session `{session_id}` was not found.")
        return AuthSessionRecord(**document)

    def delete_auth_sessions_for_user(self, user_id: str) -> None:
        documents = self.collections.auth_sessions.find({"user_id": user_id})
        for document in documents:
            session_id = document.get("session_id")
            if isinstance(session_id, str):
                self.collections.auth_sessions.delete_one({"session_id": session_id})

    def revoke_auth_sessions_for_user(self, user_id: str, *, now) -> None:
        documents = self.collections.auth_sessions.find({"user_id": user_id})
        for document in documents:
            record = AuthSessionRecord(**document)
            self.save_auth_session(
                AuthSessionRecord(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    status="revoked",
                    expires_at=record.expires_at,
                    last_seen_at=record.last_seen_at,
                    created_at=record.created_at,
                    updated_at=now,
                )
            )
