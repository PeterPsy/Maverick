"""RFC 9110 entity-tag parsing used by conditional app responses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityTag:
    """One parsed HTTP entity-tag."""

    opaque: str
    weak: bool = False


def parse_entity_tag_list(value: str) -> tuple[EntityTag, ...] | str | None:
    """Parse ``If-None-Match`` syntax, returning ``*`` or a tag tuple.

    A malformed field is ignored by callers, as required for ordinary HTTP
    request preconditions. Commas inside a quoted opaque tag are preserved.
    """

    text = str(value or "").strip()
    if not text:
        return None
    if text == "*":
        return "*"
    if "*" in text:
        return None

    tags: list[EntityTag] = []
    position = 0
    length = len(text)
    while position < length:
        while position < length and text[position] in " \t":
            position += 1
        weak = text.startswith("W/", position)
        if weak:
            position += 2
        if position >= length or text[position] != '"':
            return None
        position += 1
        opaque_start = position
        while position < length and text[position] != '"':
            codepoint = ord(text[position])
            if codepoint < 0x21 or codepoint == 0x7F:
                return None
            position += 1
        if position >= length:
            return None
        tags.append(EntityTag(opaque=text[opaque_start:position], weak=weak))
        position += 1
        while position < length and text[position] in " \t":
            position += 1
        if position == length:
            break
        if text[position] != ",":
            return None
        position += 1
        if position == length:
            return None
    return tuple(tags) if tags else None


def parse_single_entity_tag(value: str) -> EntityTag | None:
    """Parse exactly one entity-tag (wildcards and lists are invalid)."""

    parsed = parse_entity_tag_list(value)
    if isinstance(parsed, tuple) and len(parsed) == 1:
        return parsed[0]
    return None


def if_none_match_matches(value: str, current_etag: str) -> bool:
    """Apply weak comparison for an ``If-None-Match`` field."""

    candidates = parse_entity_tag_list(value)
    current = parse_single_entity_tag(current_etag)
    if current is None or candidates is None:
        return False
    if candidates == "*":
        return True
    return any(candidate.opaque == current.opaque for candidate in candidates)


def if_range_matches(value: str, current_etag: str) -> bool:
    """Return true only for an exact strong ETag ``If-Range`` validator."""

    candidate = parse_single_entity_tag(value)
    current = parse_single_entity_tag(current_etag)
    return bool(candidate and current and not candidate.weak and not current.weak and candidate.opaque == current.opaque)


def strong_etag(value: str, *, fallback: str = "resource") -> str:
    """Format a backend revision as a safe strong HTTP entity-tag."""

    text = str(value or "").strip()
    parsed = parse_single_entity_tag(text)
    if parsed is not None:
        text = parsed.opaque
    else:
        if text.startswith("W/"):
            text = text[2:].strip()
        text = text.strip('"')
    clean = "".join(character for character in text if ord(character) >= 0x21 and character not in {'"', "\x7f"})
    return f'"{clean or fallback}"'
