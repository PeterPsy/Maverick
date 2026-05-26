"""Local mock provider metadata."""

from __future__ import annotations

from pathlib import Path

from drafts import local_send_draft
from store import get_thread, list_threads, mark_read, modify_labels, sync_threads

from .base import ProviderCapability


class MockMailProvider:
    provider_id = "mock"

    def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability("explicit_seed", True, "Provides deterministic local thread and message records only after explicit bootstrap."),
            ProviderCapability("local_drafts", True, "Creates local drafts and dry-run send previews."),
            ProviderCapability("real_delivery", False, "Does not send email through an external provider."),
        ]

    def list_threads(self, data_root: Path, payload: dict[str, object]) -> list[dict[str, object]]:
        return list_threads(data_root, payload)

    def get_thread(
        self,
        data_root: Path,
        thread_id: str,
        max_body_chars: int = 8000,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return get_thread(data_root, thread_id, max_body_chars=max_body_chars)

    def modify_labels(
        self,
        data_root: Path,
        thread_id: str,
        add: object = None,
        remove: object = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return modify_labels(data_root, thread_id, add=add, remove=remove)

    def mark_read(
        self,
        data_root: Path,
        thread_id: str,
        read: bool = True,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return mark_read(data_root, thread_id, read=read)

    def send_draft(
        self,
        data_root: Path,
        draft_id: str,
        confirm: bool = False,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return local_send_draft(data_root, draft_id, confirm=confirm)

    def sync_incremental(
        self,
        data_root: Path,
        connection_id: str | None = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return sync_threads(data_root, connection_id)

    def fetch_attachment(
        self,
        data_root: Path,
        attachment_id: str,
        app_secrets: dict[str, object] | None = None,
        metadata_only: bool = True,
        max_bytes: int | None = None,
        save_to_storage: bool = False,
        generated_storage_root: Path | None = None,
    ) -> dict[str, object]:
        return {
            "attachment_id": attachment_id,
            "status": "metadata_only",
            "detail": "The mock provider stores attachment metadata only and has no binary attachment fetch.",
        }
