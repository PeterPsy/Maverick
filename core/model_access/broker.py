"""Private Unix broker for sidecar model access without Maverick cognition."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import secrets
import stat
from threading import Lock, Thread
from typing import Iterable

from core.apps.sidecar_quarantine import require_sidecar_not_quarantined
from core.model_access.api_proxy import ModelApiProxy
from core.model_access.catalog import build_model_access_catalog
from core.model_access.cancellation import CancellationSignal
from core.model_access.cli_proxy import CodexCliExecutor
from core.model_access.http_server import ThreadingUnixModelAccessServer
from core.model_access.models import (
    ModelAccessCatalog,
    ModelAccessLease,
    ModelAccessScope,
    ModelApiTransport,
    ModelCliExecutor,
)


_SOCKET_MOUNT_PATH = "/model-access/broker.sock"
_BROKERS_LOCK = Lock()
_BROKERS: dict[Path, "ModelAccessBroker"] = {}
logger = logging.getLogger(__name__)


@dataclass
class _LeaseRecord:
    scope: ModelAccessScope
    cancellations: set[CancellationSignal] = field(default_factory=set)


class ModelAccessBroker:
    """Own scoped leases, catalog lookup, API forwarding, and CLI supervision."""

    def __init__(
        self,
        state,
        *,
        socket_path: Path,
        api_transport: ModelApiTransport | None = None,
        cli_executor: ModelCliExecutor | None = None,
    ) -> None:
        self.state = state
        self.socket_path = Path(socket_path)
        self.api_proxy = ModelApiProxy(state, transport=api_transport)
        self.cli_executor = cli_executor or CodexCliExecutor(repository_root=state.repository_root)
        self._lock = Lock()
        self._leases: dict[str, _LeaseRecord] = {}
        self._server: ThreadingUnixModelAccessServer | None = None
        self._thread: Thread | None = None
        self._stopped = False

    def catalog(self, scope: ModelAccessScope) -> ModelAccessCatalog:
        """Resolve the live Core-owned catalog for one authorized lease scope."""
        return build_model_access_catalog(self.state, scope)

    def start(self) -> None:
        """Bind synchronously so sidecar prewarm can issue a lease immediately."""
        directory = self.socket_path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            metadata = self.socket_path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISSOCK(metadata.st_mode):
                raise RuntimeError("model-access socket path is unsafe")
            self.socket_path.unlink()
        self._server = ThreadingUnixModelAccessServer(str(self.socket_path), self)
        self.socket_path.chmod(0o600)
        self._thread = Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="maverick-model-access-broker",
            daemon=True,
        )
        self._thread.start()

    def issue(
        self,
        *,
        workspace_id: str,
        app_id: str,
        sidecar_id: str,
        data_root: Path,
        api: bool,
        cli: Iterable[str],
    ) -> ModelAccessLease:
        if self._stopped or self._server is None:
            raise RuntimeError("model-access broker is unavailable")
        require_sidecar_not_quarantined(
            self.state.app_store,
            workspace_id=workspace_id,
            app_id=app_id,
        )
        token = secrets.token_urlsafe(48)
        scope = ModelAccessScope(
            workspace_id=workspace_id,
            app_id=app_id,
            sidecar_id=sidecar_id,
            data_root=Path(data_root).resolve(strict=True),
            api=bool(api),
            cli=tuple(cli),
        )
        with self._lock:
            self._leases[token] = _LeaseRecord(scope=scope)

        try:
            require_sidecar_not_quarantined(
                self.state.app_store,
                workspace_id=workspace_id,
                app_id=app_id,
            )
        except Exception:
            self._revoke_token(token)
            raise

        def release() -> None:
            self._revoke_token(token)

        return ModelAccessLease(
            socket_directory=self.socket_path.parent,
            socket_path=self.socket_path,
            sandbox_socket_path=_SOCKET_MOUNT_PATH,
            token=token,
            release=release,
        )

    def authorize(
        self,
        authorization: str,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> ModelAccessScope:
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise PermissionError("model-access capability missing")
        token = authorization[len(prefix) :]
        with self._lock:
            lease = self._leases.get(token)
            if lease is not None and cancellation is not None:
                lease.cancellations.add(cancellation)
        if lease is None:
            raise PermissionError("model-access capability invalid")
        try:
            require_sidecar_not_quarantined(
                self.state.app_store,
                workspace_id=lease.scope.workspace_id,
                app_id=lease.scope.app_id,
            )
        except Exception:
            self._revoke_token(token)
            raise PermissionError("model-access capability quarantined") from None
        return lease.scope

    def release_authorization(
        self,
        authorization: str,
        *,
        cancellation: CancellationSignal | None,
    ) -> None:
        if cancellation is None or not authorization.startswith("Bearer "):
            return
        token = authorization.removeprefix("Bearer ")
        with self._lock:
            lease = self._leases.get(token)
            if lease is not None:
                lease.cancellations.discard(cancellation)

    def revoke_scope(self, *, workspace_id: str, app_id: str) -> int:
        """Revoke matching tokens and cancel their already-open requests."""
        with self._lock:
            tokens = [
                token
                for token, lease in self._leases.items()
                if lease.scope.workspace_id == workspace_id
                and lease.scope.app_id == app_id
            ]
            leases = [self._leases.pop(token) for token in tokens]
        for lease in leases:
            for cancellation in lease.cancellations:
                cancellation.set()
        return len(leases)

    def _revoke_token(self, token: str) -> None:
        with self._lock:
            lease = self._leases.pop(token, None)
        if lease is not None:
            for cancellation in lease.cancellations:
                cancellation.set()

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            leases = list(self._leases.values())
            self._leases.clear()
        for lease in leases:
            for cancellation in lease.cancellations:
                cancellation.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.socket_path.unlink(missing_ok=True)
        try:
            self.socket_path.parent.rmdir()
        except OSError:
            pass

def start_model_access_broker_server(state, *, shutdown_controller) -> ModelAccessBroker | None:
    """Start one Core-owned broker before any declarative sidecar prewarm."""
    repository_root = Path(state.repository_root).resolve(strict=True)
    socket_path = repository_root / "tmp" / "maverick-model-access" / "broker.sock"
    with _BROKERS_LOCK:
        existing = _BROKERS.get(repository_root)
        if existing is not None and not existing._stopped:
            return existing
        broker = ModelAccessBroker(state, socket_path=socket_path)
        try:
            broker.start()
        except Exception:
            logger.exception("Optional model-access broker could not start.")
            return None
        _BROKERS[repository_root] = broker

    def cleanup() -> None:
        broker.stop()
        with _BROKERS_LOCK:
            if _BROKERS.get(repository_root) is broker:
                _BROKERS.pop(repository_root, None)

    shutdown_controller.register_cleanup(cleanup)
    return broker


def issue_model_access_lease(
    repository_root: Path,
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    data_root: Path,
    api: bool,
    cli: Iterable[str],
) -> ModelAccessLease | None:
    """Return an optional lease; absence degrades only the bridge."""
    root = Path(repository_root).resolve(strict=True)
    with _BROKERS_LOCK:
        broker = _BROKERS.get(root)
    if broker is None:
        return None
    return broker.issue(
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        data_root=data_root,
        api=api,
        cli=cli,
    )


def revoke_model_access_leases(
    repository_root: Path,
    *,
    workspace_id: str,
    app_id: str,
) -> int:
    """Revoke one quarantined app's model tokens without affecting other scopes."""
    root = Path(repository_root).resolve(strict=True)
    with _BROKERS_LOCK:
        broker = _BROKERS.get(root)
    if broker is None:
        return 0
    return broker.revoke_scope(workspace_id=workspace_id, app_id=app_id)
