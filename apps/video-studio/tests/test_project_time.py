"""Exact time-model tests for fractional rates, VFR, long timelines, and audio."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from project_ir.temporal import (  # noqa: E402
    Rational,
    Rounding,
    frames_to_microseconds,
    frames_to_samples,
    microseconds_to_frames,
    microseconds_to_pts,
    pts_to_microseconds,
    rescale_timestamp,
    round_fraction,
    samples_to_frames,
)


class RationalTimeTest(unittest.TestCase):
    def test_broadcast_fractional_frame_rates_use_exact_integer_authority(self) -> None:
        cases = (
            (Rational(24000, 1001), 41708),
            (Rational(30000, 1001), 33367),
            (Rational(60000, 1001), 16683),
        )
        for rate, expected_one_frame_us in cases:
            with self.subTest(rate=rate):
                self.assertEqual(frames_to_microseconds(1, rate), expected_one_frame_us)
                self.assertEqual(microseconds_to_frames(expected_one_frame_us, rate), 1)
                self.assertEqual(rate.to_dict(), Rational.from_dict(rate.to_dict()).to_dict())

    def test_rounding_is_explicit_including_negative_ties(self) -> None:
        self.assertEqual(round_fraction(Fraction(5, 2), Rounding.NEAREST_TIES_TO_EVEN), 2)
        self.assertEqual(round_fraction(Fraction(7, 2), Rounding.NEAREST_TIES_TO_EVEN), 4)
        self.assertEqual(round_fraction(Fraction(-5, 2), Rounding.NEAREST_TIES_TO_EVEN), -2)
        self.assertEqual(round_fraction(Fraction(-7, 2), Rounding.NEAREST_TIES_TO_EVEN), -4)
        self.assertEqual(round_fraction(Fraction(-3, 2), Rounding.FLOOR), -2)
        self.assertEqual(round_fraction(Fraction(-3, 2), Rounding.CEIL), -1)

    def test_frame_boundaries_have_deterministic_floor_and_ceil(self) -> None:
        rate = Rational(24000, 1001)
        boundary_us = frames_to_microseconds(1000, rate, Rounding.FLOOR)

        self.assertEqual(microseconds_to_frames(boundary_us, rate, Rounding.FLOOR), 999)
        self.assertEqual(microseconds_to_frames(boundary_us, rate, Rounding.CEIL), 1000)
        exact_ceiling = frames_to_microseconds(1000, rate, Rounding.CEIL)
        self.assertEqual(microseconds_to_frames(exact_ceiling, rate, Rounding.FLOOR), 1000)

    def test_long_timelines_and_repeated_absolute_conversions_do_not_drift(self) -> None:
        rate = Rational(30000, 1001)
        ten_hours_frames = 10 * 60 * 60 * 30000 // 1001
        current = ten_hours_frames
        for _ in range(1000):
            current = microseconds_to_frames(frames_to_microseconds(current, rate), rate)
        self.assertEqual(current, ten_hours_frames)

        exact = Fraction(ten_hours_frames * 1001 * 1_000_000, 30000)
        self.assertLessEqual(abs(frames_to_microseconds(ten_hours_frames, rate) - exact), Fraction(1, 2))

    def test_vfr_pts_use_source_time_base_not_nominal_frame_rate(self) -> None:
        time_base = Rational(1, 90000)
        pts = [0, 3000, 6100, 9200, 12250, 15350]
        converted = [pts_to_microseconds(value, time_base) for value in pts]

        self.assertEqual(converted, sorted(set(converted)))
        for source, microseconds in zip(pts, converted, strict=True):
            self.assertLessEqual(abs(microseconds_to_pts(microseconds, time_base) - source), 1)
        self.assertEqual(rescale_timestamp(90000, time_base, Rational(1, 48000)), 48000)

    def test_audio_sample_conversion_avoids_cumulative_drift(self) -> None:
        for rate in (Rational(24000, 1001), Rational(30000, 1001), Rational(60000, 1001)):
            frames = 12 * 60 * 60 * rate.numerator // rate.denominator
            samples = frames_to_samples(frames, rate, 48000)
            exact_samples = Fraction(frames * rate.denominator * 48000, rate.numerator)

            self.assertLessEqual(abs(samples - exact_samples), Fraction(1, 2))
            self.assertEqual(samples_to_frames(samples, 48000, rate), frames)
            repeated = frames
            for _ in range(1000):
                repeated = samples_to_frames(frames_to_samples(repeated, rate, 48000), 48000, rate)
            self.assertEqual(repeated, frames)

    def test_invalid_float_and_non_positive_rates_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            Rational(23.976, 1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Rational(24000, 0)
        with self.assertRaises(ValueError):
            frames_to_microseconds(1, Rational(0, 1))


if __name__ == "__main__":
    unittest.main()
