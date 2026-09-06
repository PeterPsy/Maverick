"""Durable, installation-bound permit revocation and non-renewable ownership."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.permit import LabExecutionPermit, require_digest, require_id
from core.certification_lab.permit_codec import SignedLabExecutionPermit, decode_permit, permit_bytes, verify_lab_permit
from core.certification_lab.private_files import require_private_path
from core.certification_lab.trust import LabPermitTrust


@dataclass(frozen=True)
class LabPermitReference:
    installation_id: str
    job_id: str
    permit_id: str
    permit_digest: str
    status_revision: int


@dataclass(frozen=True)
class LabSessionOwnership:
    reference: LabPermitReference
    session_id: str
    scenario_id: str
    token: str

    def __repr__(self):
        return f"LabSessionOwnership(session_id={self.session_id!r}, token=<redacted>)"


class LabPermitStore:
    @classmethod
    def create(cls, path: Path, *, trust: LabPermitTrust):
        require_private_path(path, must_exist=False)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript("""
                PRAGMA synchronous=FULL;
                CREATE TABLE installation (id TEXT PRIMARY KEY);
                CREATE TABLE permits (id TEXT PRIMARY KEY, document BLOB NOT NULL,
                    signature TEXT NOT NULL, digest TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','revoked')));
                CREATE TABLE sessions (id TEXT PRIMARY KEY, permit_id TEXT NOT NULL,
                    token_digest TEXT NOT NULL, scenario_id TEXT NOT NULL, binding_digest TEXT,
                    status TEXT NOT NULL CHECK(status IN ('claimed','completed')));
            """)
            connection.execute("INSERT INTO installation VALUES (?)", (trust.installation_id,))
            connection.commit()
        return cls(path, trust=trust)

    def __init__(self, path: Path, *, trust: LabPermitTrust):
        self.path = Path(path)
        self.trust = trust
        with self._connection():
            pass

    @contextmanager
    def _connection(self):
        connection = None
        try:
            require_private_path(self.path)
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT id FROM installation").fetchall() != [(self.trust.installation_id,)]:
                raise LabAuthorizationError("lab_installation_mismatch")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError) as error:
            raise LabAuthorizationError("lab_permit_store_unavailable") from error
        finally:
            if connection is not None:
                connection.close()

    def install(self, signed: SignedLabExecutionPermit) -> LabPermitReference:
        permit = self._verify(signed)
        content = permit_bytes(permit)
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM permits WHERE id=?", (permit.permit_id,)).fetchone():
                raise LabAuthorizationError("lab_permit_already_exists")
            connection.execute("INSERT INTO permits VALUES (?, ?, ?, ?, 1, 'active')",
                               (permit.permit_id, content, signed.signature, signed.digest))
        return LabPermitReference(permit.installation_id, permit.job_id, permit.permit_id, signed.digest, 1)

    def resolve(self, reference: LabPermitReference, *, now=None) -> LabExecutionPermit:
        with self._connection() as connection:
            return self._resolve(connection, reference, now=now)

    def _resolve(self, connection, reference, *, now=None):
        if not isinstance(reference, LabPermitReference) or reference.installation_id != self.trust.installation_id:
            raise LabAuthorizationError("lab_installation_mismatch")
        row = connection.execute("SELECT document, signature, digest, revision, status FROM permits WHERE id=?",
                                 (reference.permit_id,)).fetchone()
        if row is None:
            raise LabAuthorizationError("lab_permit_missing")
        if row[4] != "active":
            raise LabAuthorizationError("lab_permit_revoked")
        if row[2:4] != (reference.permit_digest, reference.status_revision):
            raise LabAuthorizationError("lab_permit_revision_changed")
        signed = SignedLabExecutionPermit(decode_permit(row[0]), row[1])
        permit = self._verify(signed, now=now)
        if (signed.digest != reference.permit_digest or permit.job_id != reference.job_id
                or permit.permit_id != reference.permit_id):
            raise LabAuthorizationError("lab_permit_identity_mismatch")
        return permit

    def _verify(self, signed, *, now=None):
        permit = signed.permit
        key = self.trust.public_key(issuer_key_id=permit.issuer_key_id,
                                    authorization_ref=permit.operator_authorization_ref)
        return verify_lab_permit(signed, public_key=key, installation_id=self.trust.installation_id, now=now)

    def revoke(self, permit_id: str, *, expected_revision: int) -> int:
        require_id(permit_id)
        if type(expected_revision) is not int or expected_revision < 1:
            raise LabAuthorizationError("lab_permit_cas_conflict")
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE permits SET status='revoked', revision=revision+1 WHERE id=? AND revision=? AND status='active'",
                (permit_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise LabAuthorizationError("lab_permit_cas_conflict")
        return expected_revision + 1

    def claim(self, reference: LabPermitReference, *, session_id: str, scenario_id: str) -> LabSessionOwnership:
        with self._connection() as connection:
            permit = self._resolve(connection, reference)
            grants = [g for g in permit.workspace.sessions if g.session_id == session_id and g.scenario_id == scenario_id]
            if len(grants) != 1 or grants[0].parent_session_id is not None:
                # Descendant execution needs its own parent-liveness protocol;
                # naming one in a permit does not implement native delegation.
                raise LabAuthorizationError("lab_session_not_granted")
            if connection.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                raise LabAuthorizationError("lab_session_already_claimed")
            count = connection.execute("SELECT COUNT(*) FROM sessions WHERE permit_id=? AND status='claimed'",
                                       (reference.permit_id,)).fetchone()[0]
            if count >= permit.max_concurrent_sessions:
                raise LabAuthorizationError("lab_session_concurrency_exceeded")
            token = secrets.token_hex(32)
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, NULL, 'claimed')",
                               (session_id, reference.permit_id, _token_digest(token), scenario_id))
        return LabSessionOwnership(reference, session_id, scenario_id, token)

    def bind(self, ownership: LabSessionOwnership, *, binding_digest: str) -> None:
        require_digest(binding_digest)
        with self._connection() as connection:
            self._owned(connection, ownership)
            cursor = connection.execute("UPDATE sessions SET binding_digest=? WHERE id=? AND binding_digest IS NULL",
                                        (binding_digest, ownership.session_id))
            if cursor.rowcount != 1:
                raise LabAuthorizationError("lab_binding_already_pinned")

    def validate_ownership(self, ownership: LabSessionOwnership, *, binding_digest: str) -> LabExecutionPermit:
        with self._connection() as connection:
            permit, row = self._owned(connection, ownership)
            if row[3] != binding_digest:
                raise LabAuthorizationError("lab_binding_identity_mismatch")
            return permit

    def complete(self, ownership: LabSessionOwnership) -> None:
        # A terminal tombstone is never a new lease. Teardown calls this only
        # after proving descendants are absent and retaining cleanup receipts.
        with self._connection() as connection:
            self._owned(connection, ownership)
            connection.execute("UPDATE sessions SET status='completed' WHERE id=?", (ownership.session_id,))

    def _owned(self, connection, ownership):
        permit = self._resolve(connection, ownership.reference)
        row = connection.execute("SELECT permit_id, token_digest, scenario_id, binding_digest, status FROM sessions WHERE id=?",
                                 (ownership.session_id,)).fetchone()
        if row is None or row[:3] != (permit.permit_id, _token_digest(ownership.token), ownership.scenario_id) or row[4] != 'claimed':
            raise LabAuthorizationError("lab_session_ownership_lost")
        return permit, row


def _token_digest(token):
    require_digest(token)
    return hashlib.sha256(token.encode()).hexdigest()
