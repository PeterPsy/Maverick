"""Closed registries for renderer-independent IR references."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationIssue, issue


@dataclass(frozen=True)
class ParameterRule:
    kinds: tuple[type, ...]
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class EffectDefinition:
    effect_id: str
    version: str
    parameters: dict[str, ParameterRule] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectRegistry:
    """Immutable-by-convention allowlists resolved by id plus version."""

    effects: dict[tuple[str, str], EffectDefinition]
    transitions: frozenset[tuple[str, str]]
    templates: frozenset[tuple[str, str]]
    fonts: frozenset[tuple[str, str]]
    easings: frozenset[str]
    compositing_modes: frozenset[str]
    fit_modes: frozenset[str]
    color_spaces: frozenset[str]

    def validate_effect(
        self,
        reference: object,
        parameters: object,
        path: str,
    ) -> list[ValidationIssue]:
        key = _reference_key(reference)
        definition = self.effects.get(key) if key else None
        if definition is None:
            return [issue("effect_not_registered", f"{path}/registry", "Effect is not registered.")]
        if not isinstance(parameters, dict):
            return [issue("effect_parameters_invalid", f"{path}/parameters", "Effect parameters must be an object.")]
        problems: list[ValidationIssue] = []
        unknown = sorted(set(parameters) - set(definition.parameters))
        if unknown:
            problems.append(
                issue(
                    "effect_parameter_unknown",
                    f"{path}/parameters",
                    "Effect contains parameters outside its registered schema.",
                    parameter_names=unknown,
                )
            )
        for name, rule in sorted(definition.parameters.items()):
            if name not in parameters:
                continue
            value = parameters[name]
            if isinstance(value, bool) and bool not in rule.kinds:
                valid_kind = False
            else:
                valid_kind = isinstance(value, rule.kinds)
            parameter_path = f"{path}/parameters/{name}"
            if not valid_kind:
                problems.append(
                    issue("effect_parameter_type", parameter_path, "Effect parameter has an invalid type.")
                )
                continue
            if isinstance(value, int) and rule.minimum is not None and value < rule.minimum:
                problems.append(
                    issue(
                        "effect_parameter_range",
                        parameter_path,
                        "Effect parameter is below its registered minimum.",
                        minimum=rule.minimum,
                    )
                )
            if isinstance(value, int) and rule.maximum is not None and value > rule.maximum:
                problems.append(
                    issue(
                        "effect_parameter_range",
                        parameter_path,
                        "Effect parameter exceeds its registered maximum.",
                        maximum=rule.maximum,
                    )
                )
            if rule.choices and value not in rule.choices:
                problems.append(
                    issue(
                        "effect_parameter_choice",
                        parameter_path,
                        "Effect parameter is outside its registered choices.",
                        choices=list(rule.choices),
                    )
                )
        return problems


def _reference_key(reference: object) -> tuple[str, str] | None:
    if not isinstance(reference, dict) or set(reference) != {"id", "version"}:
        return None
    identifier = reference.get("id")
    version = reference.get("version")
    if not isinstance(identifier, str) or not isinstance(version, str):
        return None
    return identifier, version


def default_registry() -> ProjectRegistry:
    integer = (int,)
    effects = {
        ("video.brightness", "1"): EffectDefinition(
            "video.brightness", "1", {"amount_permille": ParameterRule(integer, -1000, 1000)}
        ),
        ("video.contrast", "1"): EffectDefinition(
            "video.contrast", "1", {"amount_permille": ParameterRule(integer, -1000, 2000)}
        ),
        ("video.saturation", "1"): EffectDefinition(
            "video.saturation", "1", {"amount_permille": ParameterRule(integer, 0, 3000)}
        ),
        ("video.blur", "1"): EffectDefinition(
            "video.blur", "1", {"radius_millipixels": ParameterRule(integer, 0, 100_000)}
        ),
        ("audio.equalizer", "1"): EffectDefinition(
            "audio.equalizer",
            "1",
            {
                "low_gain_millibels": ParameterRule(integer, -2400, 2400),
                "mid_gain_millibels": ParameterRule(integer, -2400, 2400),
                "high_gain_millibels": ParameterRule(integer, -2400, 2400),
            },
        ),
    }
    return ProjectRegistry(
        effects=effects,
        transitions=frozenset(
            {
                ("transition.cut", "1"),
                ("transition.dissolve", "1"),
                ("transition.dip-to-color", "1"),
                ("transition.wipe", "1"),
                ("transition.audio-crossfade", "1"),
            }
        ),
        templates=frozenset({("title.basic", "1"), ("lower-third.basic", "1")}),
        fonts=frozenset({("inter", "1"), ("noto-sans", "1"), ("noto-sans-mono", "1")}),
        easings=frozenset(
            {"linear", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end"}
        ),
        compositing_modes=frozenset({"source-over", "multiply", "screen", "overlay", "add"}),
        fit_modes=frozenset({"contain", "cover", "fill", "none"}),
        color_spaces=frozenset({"srgb", "rec709", "display-p3"}),
    )
