"""Deterministic cache-control contract for the real platform benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

import benchmark_opendesign_platform as benchmark  # noqa: E402


class OpenDesignPlatformBenchmarkTests(unittest.TestCase):
    def test_runtime_repair_cache_control_covers_every_signed_source_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-platform-cache-") as temporary:
            source = Path(temporary)
            asset: dict[str, object] = {}
            expected_bytes = 0
            for index, field in enumerate(benchmark.RUNTIME_SOURCE_FILE_FIELDS, start=1):
                name = f"input-{index}.bin"
                content = bytes([index]) * index
                (source / name).write_bytes(content)
                asset[field] = name
                expected_bytes += len(content)
            calls: list[tuple[int, int, int, int]] = []
            fsync_calls: list[int] = []
            with (
                patch.object(
                    benchmark.os,
                    "fsync",
                    side_effect=lambda descriptor: fsync_calls.append(descriptor),
                ),
                patch.object(
                    benchmark.os,
                    "posix_fadvise",
                    side_effect=lambda *arguments: calls.append(arguments),
                ),
            ):
                result = benchmark._control_runtime_source_cache(source, asset=asset)

        self.assertEqual(result["policy"], "posix_fadvise_dontneed")
        self.assertTrue(result["controlled"])
        self.assertTrue(result["fsync_before_eviction"])
        self.assertEqual(result["file_count"], len(benchmark.RUNTIME_SOURCE_FILE_FIELDS))
        self.assertEqual(result["bytes"], expected_bytes)
        self.assertFalse(result["inside_repair_timer"])
        self.assertEqual(len(calls), len(benchmark.RUNTIME_SOURCE_FILE_FIELDS))
        self.assertEqual(len(fsync_calls), len(benchmark.RUNTIME_SOURCE_FILE_FIELDS))
        self.assertTrue(
            all(call[1:] == (0, 0, benchmark.os.POSIX_FADV_DONTNEED) for call in calls)
        )
        self.assertNotIn(str(source), json.dumps(result, sort_keys=True))

    def test_runtime_repair_cache_control_fails_instead_of_claiming_an_unknown_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-platform-cache-missing-") as temporary:
            source = Path(temporary)
            asset = {
                field: f"missing-{index}.bin"
                for index, field in enumerate(benchmark.RUNTIME_SOURCE_FILE_FIELDS)
            }
            with self.assertRaises(benchmark.PlatformBenchmarkError):
                benchmark._control_runtime_source_cache(source, asset=asset)

    def test_runtime_repair_cache_control_requires_the_kernel_eviction_primitive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-platform-cache-api-") as temporary:
            with (
                patch.object(benchmark.os, "posix_fadvise", None),
                self.assertRaisesRegex(
                    benchmark.PlatformBenchmarkError,
                    "requires POSIX_FADV_DONTNEED",
                ),
            ):
                benchmark._control_runtime_source_cache(Path(temporary), asset={})


if __name__ == "__main__":
    unittest.main()
