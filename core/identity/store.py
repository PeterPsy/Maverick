"""Mongo-oriented storage helpers for identity-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.identity.errors import SessionNotFoundError, UserNotFoundError
from core.identity.models import AuthSessionRecord, PasswordCredentialRecord, UserRecord


class MongoCollection(Protocol):
    """Minimal collection protocol used by the control-plane stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...


@dataclass(frozen=True)
class IdentityCollections:
    """Mongo collection bundle for identity persistence."""

    users: MongoCollection
    credentials: MongoCollection
    auth_sessions: MongoCollection


class MongoIdentityStore:
    """Persist identity-domain records in Mongo-style collections."""

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

    def save_password_credential(self, record: PasswordCredentialRecord) -> PasswordCredentialRecord:
        payload = asdict(record)
        self.collections.credentials.update_one({"user_id": record.user_id}, {"$set": payload}, upsert=True)
        return record

    def get_password_credential(self, user_id: str) -> PasswordCredentialRecord:
        document = self.collections.credentials.find_one({"user_id": user_id})
        if document is None:
            raise UserNotFoundError(f"No password credential exists for user `{user_id}`.")
        return PasswordCredentialRecord(**document)

    def save_auth_session(self, record: AuthSessionRecord) -> AuthSessionRecord:
        payload = asdict(record)
        self.collections.auth_sessions.update_one({"session_id": record.session_id}, {"$set": payload}, upsert=True)
        return record

    def get_auth_session(self, session_id: str) -> AuthSessionRecord:
        document = self.collections.auth_sessions.find_one({"session_id": session_id})
        if document is None:
            raise SessionNotFoundError(f"Auth session `{session_id}` was not found.")
        return AuthSessionRecord(**document)
