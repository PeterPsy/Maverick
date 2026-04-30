"""Shared helpers for SDK app templates."""

from __future__ import annotations

import re


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
ENTITY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def title_from_slug(app_id: str) -> str:
    """Return a display title from a kebab-case app id."""
    return " ".join(part.capitalize() for part in app_id.split("-"))


def snake_from_slug(app_id: str) -> str:
    """Return a snake-case identifier from a kebab-case app id."""
    return app_id.replace("-", "_")


def normalize_entities(entities: list[str] | None) -> list[str]:
    """Normalize and validate entity names for generated entity apps."""
    values = [str(entity).strip().lower() for entity in entities or ["record"]]
    normalized: list[str] = []
    for value in values:
        snake = value.replace("-", "_")
        if not ENTITY_PATTERN.fullmatch(snake):
            raise ValueError(f"Entity `{value}` must use lowercase snake_case or kebab-case.")
        if snake not in normalized:
            normalized.append(snake)
    return normalized
