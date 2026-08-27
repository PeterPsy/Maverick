"""Request-scoped read-through snapshot for provider governance records."""

from __future__ import annotations

from functools import cache

from core.providers.store import ProviderStore


class ProviderReadSnapshot:
    """Reuse immutable/read-only provider records during one projection request.

    The snapshot is deliberately short lived.  It avoids reparsing the same JSON
    collections for every runtime session while keeping mutations and subsequent
    requests on the authoritative store.
    """

    def __init__(self, store: ProviderStore) -> None:
        self._store = store

    @cache
    def get_agentic_profile_definition(self, definition_id: str, revision: str):
        return self._store.get_agentic_profile_definition(definition_id, revision)

    @cache
    def get_agentic_profile_definition_status(self, definition_id: str, revision: str):
        return self._store.get_agentic_profile_definition_status(definition_id, revision)

    @cache
    def get_workspace_agentic_profile_binding(self, binding_id: str):
        return self._store.get_workspace_agentic_profile_binding(binding_id)

    @cache
    def get_capability_evidence(self, evidence_digest: str):
        return self._store.get_capability_evidence(evidence_digest)

    @cache
    def get_capability_certificate(self, certificate_id: str):
        return self._store.get_capability_certificate(certificate_id)

    @cache
    def get_capability_certificate_status(self, certificate_id: str):
        return self._store.get_capability_certificate_status(certificate_id)

    @cache
    def get_provider_binding(self, binding_id: str):
        return self._store.get_provider_binding(binding_id)

    @cache
    def list_provider_bindings(
        self,
        *,
        workspace_id: str | None = None,
        provider_id: str | None = None,
    ):
        return self._store.list_provider_bindings(
            workspace_id=workspace_id,
            provider_id=provider_id,
        )

    def __getattr__(self, name: str):
        return getattr(self._store, name)
