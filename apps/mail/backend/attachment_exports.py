"""Filtered Storage export, deduplication and document-part summaries."""

from pathlib import Path
import base64
import binascii
import hashlib
import re
import unicodedata

from storage_attachments import save_attachment_to_storage


def save_thread_attachments(data_root: Path, payload: dict[str, object], thread: dict[str, object], provider: object) -> dict[str, object]:
    thread_id = str(thread["id"])
    max_bytes = _optional_bounded_int(payload.get("max_bytes"), 1, 10_000_000) or 10_000_000
    dedupe = bool(payload.get("dedupe", True))
    target_folder = payload.get("target_folder") or "storage/generated/mail/attachments"
    mode = payload.get("mode") or "versioned"
    saved: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    source_attachments: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    generated_storage_root = _optional_path(payload.get("_generated_storage_root"))
    for message in thread.get("messages", []):
        if not isinstance(message, dict):
            continue
        for attachment in message.get("attachments", []):
            if not isinstance(attachment, dict):
                continue
            filename = str(attachment.get("filename") or "")
            size_bytes = int(attachment.get("size_bytes") or 0)
            source_attachments.append(
                {
                    "attachment_id": attachment.get("id"),
                    "message_id": message.get("id"),
                    "filename": filename,
                    "content_type": attachment.get("content_type") or "",
                    "size_bytes": size_bytes,
                }
            )
            if not _attachment_filter_matches(attachment, payload):
                skipped.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "filename": filename,
                        "content_type": attachment.get("content_type") or "",
                        "size_bytes": size_bytes,
                        "reason": "filtered",
                    }
                )
                continue
            fetch = provider.fetch_attachment(
                data_root,
                str(attachment["id"]),
                app_secrets=(payload.get("_app_secrets") if isinstance(payload.get("_app_secrets"), dict) else {}),
                metadata_only=False,
                max_bytes=max_bytes,
                save_to_storage=True,
                generated_storage_root=generated_storage_root,
                storage_target_folder=target_folder,
                storage_mode=mode,
                skip_sha256s=seen_hashes if dedupe else None,
            )
            if fetch.get("status") == "duplicate_sha256":
                sha256 = str(fetch.get("sha256") or "")
                skipped.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "filename": filename,
                        "content_type": attachment.get("content_type") or "",
                        "size_bytes": fetch.get("size_bytes", size_bytes),
                        "reason": "duplicate_sha256",
                        "sha256": sha256,
                    }
                )
                continue
            if fetch.get("status") == "saved":
                storage_ref = fetch.get("storage_ref") if isinstance(fetch.get("storage_ref"), dict) else {}
                sha256 = str(storage_ref.get("sha256") or fetch.get("sha256") or "")
                if sha256:
                    seen_hashes.add(sha256)
                saved.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "message_id": message.get("id"),
                        "thread_id": thread_id,
                        "filename": filename,
                        "content_type": attachment.get("content_type") or "",
                        "size_bytes": storage_ref.get("size_bytes", fetch.get("size_bytes", size_bytes)),
                        "sha256": sha256,
                        "workspace_relative_path": storage_ref.get("workspace_relative_path"),
                        "source": {
                            "message_id": message.get("id"),
                            "sent_at": message.get("sent_at"),
                            "sender": message.get("sender"),
                        },
                    }
                )
                continue
            if fetch.get("status") != "fetched":
                skipped.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "filename": filename,
                        "reason": fetch.get("status"),
                        "detail": fetch.get("detail"),
                    }
                )
                continue
            try:
                attachment_bytes = _attachment_bytes_from_fetch(fetch)
            except ValueError as error:
                skipped.append(
                    {"attachment_id": attachment.get("id"), "filename": filename, "reason": "invalid_payload", "detail": str(error)}
                )
                continue
            sha256 = hashlib.sha256(attachment_bytes).hexdigest()
            if dedupe and sha256 and sha256 in seen_hashes:
                skipped.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "filename": filename,
                        "content_type": attachment.get("content_type") or "",
                        "size_bytes": fetch.get("size_bytes", size_bytes),
                        "reason": "duplicate_sha256",
                        "sha256": sha256,
                    }
                )
                continue
            seen_hashes.add(sha256)
            storage_ref = save_attachment_to_storage(
                data_root,
                attachment_id=str(attachment["id"]),
                filename=filename,
                content_type=str(attachment.get("content_type") or "application/octet-stream"),
                attachment_bytes=attachment_bytes,
                generated_storage_root=generated_storage_root,
                target_folder=target_folder,
                mode=mode,
            )
            saved.append(
                {
                    "attachment_id": attachment.get("id"),
                    "message_id": message.get("id"),
                    "thread_id": thread_id,
                    "filename": filename,
                    "content_type": attachment.get("content_type") or "",
                    "size_bytes": storage_ref.get("size_bytes", fetch.get("size_bytes", size_bytes)),
                    "sha256": sha256,
                    "workspace_relative_path": storage_ref.get("workspace_relative_path"),
                    "source": {
                        "message_id": message.get("id"),
                        "sent_at": message.get("sent_at"),
                        "sender": message.get("sender"),
                    },
                }
            )
    attachment_summary = _attachment_save_summary(source_attachments, saved, skipped)
    document_part_hints = _document_part_hints(source_attachments)
    return {
        "status": "saved",
        "thread_id": thread_id,
        "target_folder": target_folder,
        "dedupe": dedupe,
        "saved": saved,
        "skipped": skipped,
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "attachment_summary": attachment_summary,
        "document_part_hints": document_part_hints,
    }


def _attachment_bytes_from_fetch(fetch: dict[str, object]) -> bytes:
    data_base64url = str(fetch.get("data_base64url") or "").strip()
    if not data_base64url:
        if int(fetch.get("size_bytes") or 0) == 0:
            return b""
        raise ValueError("Provider did not return attachment bytes.")
    try:
        return base64.urlsafe_b64decode(data_base64url + ("=" * (-len(data_base64url) % 4)))
    except (binascii.Error, ValueError) as error:
        raise ValueError("Provider returned invalid attachment bytes.") from error


def _attachment_filter_matches(attachment: dict[str, object], payload: dict[str, object]) -> bool:
    filename = str(attachment.get("filename") or "")
    content_type = str(attachment.get("content_type") or "")
    size_bytes = int(attachment.get("size_bytes") or 0)
    name_contains = _optional_string(payload.get("filename_contains"))
    if name_contains and name_contains.casefold() not in filename.casefold():
        return False
    extensions = _string_filter_set(payload.get("extensions") or payload.get("extension"))
    if extensions:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in extensions:
            return False
    content_types = _string_filter_set(payload.get("content_types") or payload.get("content_type"))
    if content_types and content_type.casefold() not in content_types:
        return False
    max_size = _optional_bounded_int(payload.get("max_size_bytes"), 1, 10_000_000_000)
    if max_size is not None and size_bytes > max_size:
        return False
    return True


def _string_filter_set(value: object) -> set[str]:
    if value in (None, ""):
        return set()
    values = value if isinstance(value, list) else [value]
    return {str(item).strip().lower().lstrip(".") for item in values if str(item).strip()}


def _attachment_save_summary(
    source_attachments: list[dict[str, object]],
    saved: list[dict[str, object]],
    skipped: list[dict[str, object]],
) -> dict[str, object]:
    filtered_count = sum(1 for item in skipped if item.get("reason") == "filtered")
    groups: dict[str, dict[str, object]] = {}
    for item in [*saved, *skipped]:
        sha256 = str(item.get("sha256") or "").strip()
        if not sha256:
            continue
        group = groups.setdefault(
            sha256,
            {
                "sha256": sha256,
                "count": 0,
                "attachment_ids": [],
                "filenames": [],
                "size_bytes": int(item.get("size_bytes") or 0),
                "workspace_relative_paths": [],
            },
        )
        group["count"] = int(group["count"]) + 1
        _append_unique(group["attachment_ids"], item.get("attachment_id"))
        _append_unique(group["filenames"], item.get("filename"))
        _append_unique(group["workspace_relative_paths"], item.get("workspace_relative_path"))
    unique_by_sha256 = sorted(groups.values(), key=lambda item: (str(item.get("filenames") or ""), str(item.get("sha256") or "")))
    duplicate_count = sum(max(0, int(item.get("count") or 0) - 1) for item in unique_by_sha256)
    return {
        "total_count": len(source_attachments),
        "matched_count": len(source_attachments) - filtered_count,
        "filtered_count": filtered_count,
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "unique_count_by_sha256": len(unique_by_sha256),
        "duplicate_count_by_sha256": duplicate_count,
        "unique_by_sha256": unique_by_sha256,
    }


def _append_unique(target: object, value: object) -> None:
    if not isinstance(target, list):
        return
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _document_part_hints(source_attachments: list[dict[str, object]]) -> list[dict[str, object]]:
    document_types = {
        "identity_card": {
            "label": "carta identita",
            "keywords": (
                "carta identita",
                "carta d identita",
                "documento identita",
                "documento d identita",
                "identity card",
                "id card",
                "carta id",
            ),
        },
        "health_card": {
            "label": "tessera sanitaria",
            "keywords": (
                "tessera sanitaria",
                "codice fiscale",
                "health card",
            ),
        },
    }
    side_keywords = {
        "front": ("fronte", "front", "davanti", "anteriore"),
        "back": ("retro", "back", "posteriore"),
    }
    detected: dict[str, dict[str, object]] = {}
    for attachment in source_attachments:
        filename = str(attachment.get("filename") or "")
        normalized = _normalized_document_name(filename)
        for document_type, spec in document_types.items():
            if not any(keyword in normalized for keyword in spec["keywords"]):
                continue
            item = detected.setdefault(
                document_type,
                {"document_type": document_type, "label": spec["label"], "present_sides": set(), "evidence_filenames": []},
            )
            _append_unique(item["evidence_filenames"], filename)
            for side, keywords in side_keywords.items():
                if any(keyword in normalized for keyword in keywords):
                    present_sides = item["present_sides"]
                    if isinstance(present_sides, set):
                        present_sides.add(side)
    hints: list[dict[str, object]] = []
    for item in detected.values():
        present = sorted(item["present_sides"]) if isinstance(item.get("present_sides"), set) else []
        if not present:
            continue
        missing = [side for side in ("front", "back") if side not in present]
        hints.append(
            {
                "document_type": item["document_type"],
                "label": item["label"],
                "present_sides": present,
                "missing_sides": missing,
                "evidence_filenames": item["evidence_filenames"],
                "severity": "warning" if missing else "info",
            }
        )
    return sorted(hints, key=lambda item: str(item.get("document_type") or ""))


def _normalized_document_name(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def _optional_bounded_int(value: object, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum:
        return None
    return min(maximum, parsed)


def _optional_string(value: object) -> str | None:
    return str(value or "").strip() or None


def _optional_path(value: object) -> Path | None:
    text = _optional_string(value)
    return Path(text) if text else None
