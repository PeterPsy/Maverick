"""Argument-sensitive effect metadata shared by executable tool surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


ToolEffectClass = Literal["read", "mutating", "destructive", "unclassified"]


@dataclass(frozen=True)
class ToolArgumentEffectMap:
    """Resolve one top-level discriminator to a fail-closed effect class."""

    argument_name: str
    omitted_effect_class: ToolEffectClass
    value_effect_classes: tuple[tuple[str, ToolEffectClass], ...]

    def resolve(self, arguments: dict[str, object]) -> ToolEffectClass:
        if self.argument_name not in arguments:
            return self.omitted_effect_class
        value = arguments.get(self.argument_name)
        if not isinstance(value, str):
            return "unclassified"
        for expected, effect_class in self.value_effect_classes:
            if value == expected:
                return effect_class
        return "unclassified"

    def as_discovery_payload(self) -> dict[str, object]:
        return {
            "argument_name": self.argument_name,
            "omitted_effect_class": self.omitted_effect_class,
            "value_effect_classes": dict(self.value_effect_classes),
        }


def resolve_tool_effect_class(
    definition,
    arguments: dict[str, object],
) -> ToolEffectClass:
    """Return the exact declared effect, keeping malformed metadata closed."""

    declared = getattr(definition, "effect_class", "unclassified")
    default: ToolEffectClass = (
        cast(ToolEffectClass, declared)
        if isinstance(declared, str) and declared in _EFFECT_CLASSES
        else "unclassified"
    )
    effect_map = getattr(definition, "argument_effects", None)
    if effect_map is None:
        return default
    if not isinstance(effect_map, ToolArgumentEffectMap):
        return "unclassified"
    resolved = effect_map.resolve(arguments)
    return resolved if resolved in _EFFECT_CLASSES else "unclassified"


_EFFECT_CLASSES = {"read", "mutating", "destructive", "unclassified"}


__all__ = [
    "ToolArgumentEffectMap",
    "ToolEffectClass",
    "resolve_tool_effect_class",
]
