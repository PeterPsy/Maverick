"""Exact rational time conversions for project and source timelines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from bisect import bisect_right
from math import gcd


MICROSECONDS_PER_SECOND = 1_000_000


class Rounding(str, Enum):
    """Deterministic rounding modes used at explicit conversion boundaries."""

    FLOOR = "floor"
    CEIL = "ceil"
    TOWARD_ZERO = "toward_zero"
    NEAREST_TIES_TO_EVEN = "nearest_ties_to_even"


@dataclass(frozen=True)
class Rational:
    """Normalized positive-denominator rational with integer authority."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or isinstance(self.denominator, bool):
            raise ValueError("Rational values must be integers.")
        if not isinstance(self.numerator, int) or not isinstance(self.denominator, int):
            raise ValueError("Rational values must be integers.")
        if self.denominator <= 0:
            raise ValueError("Rational denominator must be positive.")
        divisor = gcd(abs(self.numerator), self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)

    @classmethod
    def from_dict(cls, value: object) -> "Rational":
        if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
            raise ValueError("Rational must contain numerator and denominator.")
        return cls(value["numerator"], value["denominator"])

    def to_dict(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}

    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


def frames_to_microseconds(
    frames: int,
    frame_rate: Rational,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(frames, "frames")
    _require_positive_rate(frame_rate, "frame rate")
    exact = Fraction(frames * frame_rate.denominator * MICROSECONDS_PER_SECOND, frame_rate.numerator)
    return round_fraction(exact, rounding)


def microseconds_to_frames(
    microseconds: int,
    frame_rate: Rational,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(microseconds, "microseconds")
    _require_positive_rate(frame_rate, "frame rate")
    exact = Fraction(microseconds * frame_rate.numerator, frame_rate.denominator * MICROSECONDS_PER_SECOND)
    return round_fraction(exact, rounding)


def pts_to_microseconds(
    pts: int,
    time_base: Rational,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(pts, "PTS")
    exact = Fraction(pts * time_base.numerator * MICROSECONDS_PER_SECOND, time_base.denominator)
    return round_fraction(exact, rounding)


def microseconds_to_pts(
    microseconds: int,
    time_base: Rational,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(microseconds, "microseconds")
    if time_base.numerator <= 0:
        raise ValueError("Time base must be positive.")
    exact = Fraction(microseconds * time_base.denominator, time_base.numerator * MICROSECONDS_PER_SECOND)
    return round_fraction(exact, rounding)


def frames_to_samples(
    frames: int,
    frame_rate: Rational,
    sample_rate: int,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(frames, "frames")
    _require_integer(sample_rate, "sample rate")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive.")
    _require_positive_rate(frame_rate, "frame rate")
    exact = Fraction(frames * frame_rate.denominator * sample_rate, frame_rate.numerator)
    return round_fraction(exact, rounding)


def samples_to_frames(
    samples: int,
    sample_rate: int,
    frame_rate: Rational,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(samples, "samples")
    _require_integer(sample_rate, "sample rate")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive.")
    _require_positive_rate(frame_rate, "frame rate")
    exact = Fraction(samples * frame_rate.numerator, sample_rate * frame_rate.denominator)
    return round_fraction(exact, rounding)


def rescale_timestamp(
    value: int,
    source_time_base: Rational,
    target_time_base: Rational,
    rounding: Rounding = Rounding.NEAREST_TIES_TO_EVEN,
) -> int:
    _require_integer(value, "timestamp")
    if source_time_base.numerator <= 0 or target_time_base.numerator <= 0:
        raise ValueError("Time bases must be positive.")
    exact = Fraction(
        value * source_time_base.numerator * target_time_base.denominator,
        source_time_base.denominator * target_time_base.numerator,
    )
    return round_fraction(exact, rounding)


def vfr_frame_to_pts(frame: int, pts_map: list[int] | tuple[int, ...]) -> int:
    """Resolve a zero-based decoded-frame index against an authoritative VFR PTS map."""

    _require_integer(frame, "frame")
    _validate_pts_map(pts_map)
    if frame < 0 or frame >= len(pts_map):
        raise ValueError("Frame lies outside the VFR PTS map.")
    return pts_map[frame]


def pts_to_vfr_frame(pts: int, pts_map: list[int] | tuple[int, ...]) -> int:
    """Resolve a source timestamp to the frame active at or immediately before it."""

    _require_integer(pts, "PTS")
    _validate_pts_map(pts_map)
    position = bisect_right(pts_map, pts) - 1
    if position < 0:
        raise ValueError("PTS precedes the VFR PTS map.")
    return position


def round_fraction(value: Fraction, rounding: Rounding) -> int:
    floor_value = value.numerator // value.denominator
    if rounding is Rounding.FLOOR:
        return floor_value
    if rounding is Rounding.CEIL:
        return -((-value.numerator) // value.denominator)
    if rounding is Rounding.TOWARD_ZERO:
        return floor_value if value >= 0 else -((-value.numerator) // value.denominator)
    remainder = value - floor_value
    if remainder < Fraction(1, 2):
        return floor_value
    if remainder > Fraction(1, 2):
        return floor_value + 1
    return floor_value if floor_value % 2 == 0 else floor_value + 1


def _require_positive_rate(value: Rational, name: str) -> None:
    if value.numerator <= 0:
        raise ValueError(f"{name.capitalize()} must be positive.")


def _require_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name.capitalize()} must be an integer.")


def _validate_pts_map(value: object) -> None:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("VFR PTS map must be a non-empty integer sequence.")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value):
        raise ValueError("VFR PTS map must contain non-negative integers.")
    if any(left >= right for left, right in zip(value, value[1:])):
        raise ValueError("VFR PTS map must be strictly increasing.")
