"""Runtime materialization helpers for structured app references."""

from __future__ import annotations


def input_text_with_app_references(*, input_text: str, app_references: list[dict[str, object]] | None) -> str:
    if not app_references:
        return input_text
    app_ids: list[str] = []
    entity_references: list[dict[str, str]] = []
    provider_text = input_text
    for reference in app_references:
        app_id = str(reference.get("app_id") or "").strip()
        label = str(reference.get("label") or "").strip()
        if app_id and app_id not in app_ids:
            app_ids.append(app_id)
        if str(reference.get("type") or "app") == "entity":
            entity_type = str(reference.get("entity_type") or "").strip()
            entity_id = str(reference.get("entity_id") or "").strip()
            if not app_id or not entity_type or not entity_id:
                continue
            provider_text = _replace_entity_reference_tokens(
                text=provider_text,
                app_id=app_id,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            entity_references.append(
                {
                    "app_id": app_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "label": label,
                    "summary": str(reference.get("summary") or "").strip(),
                    "deep_link": str(reference.get("deep_link") or "").strip(),
                    "exists": "false" if reference.get("exists") is False else "",
                }
            )
            continue
        if app_id:
            for token in [f"@{label}" if label else "", f"@{app_id}"]:
                if token:
                    provider_text = provider_text.replace(token, f"app_id:{app_id}")
    if not app_ids:
        return input_text
    reference_lines = ["Referenced apps:"] + [f"- app_id: {app_id}" for app_id in app_ids]
    if entity_references:
        reference_lines.extend(["", "Referenced app-owned records:"])
        for reference in entity_references:
            reference_lines.extend(
                [
                    f"- app_id: {reference['app_id']}",
                    f"  entity_type: {reference['entity_type']}",
                    f"  entity_id: {reference['entity_id']}",
                ]
            )
            if reference["label"]:
                reference_lines.append(f"  label: {reference['label']}")
            if reference["summary"]:
                reference_lines.append(f"  summary: {reference['summary']}")
            if reference["deep_link"]:
                reference_lines.append(f"  deep_link: {reference['deep_link']}")
            if reference["exists"]:
                reference_lines.append("  exists: false")
    return f"{provider_text.rstrip()}\n\n" + "\n".join(reference_lines)


def _replace_entity_reference_tokens(*, text: str, app_id: str, entity_type: str, entity_id: str) -> str:
    marker = f"[ref:{app_id}/{entity_type}/{entity_id}]"
    replacement = f"app_ref:{app_id}/{entity_type}/{entity_id}"
    result = text
    search_from = 0
    while search_from < len(result):
        marker_start = result.find(marker, search_from)
        if marker_start < 0:
            break
        mention_start = _entity_reference_mention_start(result, marker_start)
        replace_start = mention_start if mention_start is not None else marker_start
        replace_end = marker_start + len(marker)
        result = f"{result[:replace_start]}{replacement}{result[replace_end:]}"
        search_from = replace_start + len(replacement)
    return result


def _entity_reference_mention_start(text: str, marker_start: int) -> int | None:
    if marker_start <= 0 or text[marker_start - 1] not in " \t":
        return None
    label_end = marker_start
    while label_end > 0 and text[label_end - 1] in " \t":
        label_end -= 1
    separator = text[label_end:marker_start]
    if not separator or any(char not in " \t" for char in separator):
        return None
    at_index = text.rfind("@", 0, label_end)
    if at_index < 0:
        return None
    if at_index > 0 and not text[at_index - 1].isspace():
        return None
    label = text[at_index + 1 : label_end].strip()
    if not label or any(char in label for char in "\r\n[]"):
        return None
    return at_index
