"""Provider boundary for Mail integrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    enabled: bool
    detail: str


class MailProvider(Protocol):
    provider_id: str

    def capabilities(self) -> list[ProviderCapability]:
        """Return provider capabilities without exposing secret material."""
        ...

    def list_threads(self, data_root: Path, payload: dict[str, object]) -> list[dict[str, object]]:
        """Return cached or provider-backed threads."""
        ...

    def get_thread(
        self,
        data_root: Path,
        thread_id: str,
        max_body_chars: int = 8000,
        max_body_html_chars: int | None = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Return one thread with bounded message bodies."""
        ...

    def modify_labels(
        self,
        data_root: Path,
        thread_id: str,
        add: object = None,
        remove: object = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Apply provider labels and update the local cache."""
        ...

    def mark_read(
        self,
        data_root: Path,
        thread_id: str,
        read: bool = True,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Mark a thread read or unread."""
        ...

    def send_draft(
        self,
        data_root: Path,
        draft_id: str,
        confirm: bool = False,
        app_secrets: dict[str, object] | None = None,
        uploaded_storage_root: Path | None = None,
        generated_storage_root: Path | None = None,
    ) -> dict[str, object]:
        """Preview or send one draft."""
        ...

    def sync_incremental(
        self,
        data_root: Path,
        connection_id: str | None = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Run an incremental provider sync into the local cache."""
        ...

    def fetch_attachment(
        self,
        data_root: Path,
        attachment_id: str,
        app_secrets: dict[str, object] | None = None,
        metadata_only: bool = True,
        max_bytes: int | None = None,
        save_to_storage: bool = False,
        generated_storage_root: Path | None = None,
        storage_target_folder: object = None,
        storage_mode: object = "versioned",
    ) -> dict[str, object]:
        """Fetch an attachment or return a clear provider limitation."""
        ...
