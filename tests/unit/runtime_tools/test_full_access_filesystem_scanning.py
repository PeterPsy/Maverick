from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.egress.classification import validated_classification
from core.runtime.full_access_filesystem import FullAccessFilesystem
from core.runtime.tool_errors import RuntimeToolError


class _CancelAfter:
    def __init__(self, checks: int) -> None:
        self.remaining = checks

    def check(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            raise RuntimeToolError("runtime_cancelled")


class FullAccessFilesystemScanningTest(unittest.TestCase):
    def test_listing_pages_are_stable_when_scandir_order_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("charlie.txt", "alpha.txt", "bravo.txt"):
                (root / name).write_text(name, encoding="utf-8")
            entries = list(os.scandir(root))
            scans = iter((entries, list(reversed(entries))))

            class _Scandir:
                def __init__(self, values):
                    self.values = values

                def __enter__(self):
                    return iter(self.values)

                def __exit__(self, *_args):
                    return False

            filesystem = FullAccessFilesystem(
                workspace_id="default",
                workspace_root=root,
            )
            with patch(
                "core.runtime.full_access_filesystem_scanner.os.scandir",
                side_effect=lambda _path: _Scandir(next(scans)),
            ):
                first = filesystem.list_entries(
                    ".",
                    max_depth=1,
                    page_size=2,
                )
                second = filesystem.list_entries(
                    ".",
                    max_depth=1,
                    page_size=2,
                    cursor=first.payload["next_cursor"],
                )

            self.assertEqual(
                [entry["name"] for entry in first.payload["entries"]],
                ["alpha.txt", "bravo.txt"],
            )
            self.assertEqual(
                [entry["name"] for entry in second.payload["entries"]],
                ["charlie.txt"],
            )
            self.assertEqual(first.payload["snapshot_id"], second.payload["snapshot_id"])

    def test_list_discards_directory_incomplete_at_physical_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(10):
                (root / f"item-{index}.txt").write_text("value", encoding="utf-8")
            filesystem = FullAccessFilesystem(
                workspace_id="default",
                workspace_root=root,
                max_scan_entries=3,
            )

            result = filesystem.list_entries(
                ".",
                max_depth=1,
                page_size=100,
            )

            self.assertEqual(result.payload["total_result_count"], 0)
            self.assertTrue(result.payload["scan_truncated"])
            self.assertEqual(result.payload["scan_entry_limit"], 3)

    def test_listing_pages_stay_stable_when_physical_limit_truncates_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "anchor.txt").write_text("anchor", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            for name in ("charlie.txt", "alpha.txt", "bravo.txt"):
                (nested / name).write_text(name, encoding="utf-8")
            root_entries = list(os.scandir(root))
            nested_entries = list(os.scandir(nested))
            scans = iter(
                (
                    root_entries,
                    nested_entries,
                    list(reversed(root_entries)),
                    list(reversed(nested_entries)),
                )
            )

            class _Scandir:
                def __init__(self, values):
                    self.values = values

                def __enter__(self):
                    return iter(self.values)

                def __exit__(self, *_args):
                    return False

            filesystem = FullAccessFilesystem(
                workspace_id="default",
                workspace_root=root,
                max_scan_entries=4,
            )
            with patch(
                "core.runtime.full_access_filesystem_scanner.os.scandir",
                side_effect=lambda _path: _Scandir(next(scans)),
            ):
                first = filesystem.list_entries(
                    ".",
                    max_depth=2,
                    page_size=1,
                ).payload
                second = filesystem.list_entries(
                    ".",
                    max_depth=2,
                    page_size=1,
                    cursor=first["next_cursor"],
                ).payload

            self.assertEqual(first["entries"][0]["name"], "anchor.txt")
            self.assertEqual(second["entries"][0]["name"], "nested")
            self.assertTrue(first["scan_truncated"])
            self.assertTrue(second["scan_truncated"])
            self.assertIsNotNone(first["next_cursor"])
            self.assertIsNone(second["next_cursor"])
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_search_bounds_reads_and_reports_partial_file_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "large.txt").write_text("needle\n" * 100, encoding="utf-8")
            filesystem = FullAccessFilesystem(
                workspace_id="default",
                workspace_root=root,
                max_search_bytes=14,
                max_search_file_bytes=14,
            )

            result = filesystem.search_text(
                ".",
                query="needle",
                max_depth=1,
                page_size=100,
            )

            self.assertEqual(result.payload["scanned_bytes"], 14)
            self.assertTrue(result.payload["scan_truncated"])
            self.assertEqual(result.payload["truncated_file_count"], 1)
            self.assertLessEqual(result.payload["total_result_count"], 2)

    def test_list_and_search_check_cooperative_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(20):
                (root / f"item-{index}.txt").write_text(
                    "needle\n",
                    encoding="utf-8",
                )
            filesystem = FullAccessFilesystem(
                workspace_id="default",
                workspace_root=root,
            )

            with self.assertRaisesRegex(RuntimeToolError, "runtime_cancelled"):
                filesystem.list_entries(
                    ".",
                    max_depth=1,
                    page_size=100,
                    execution_control=_CancelAfter(4),
                )
            with self.assertRaisesRegex(RuntimeToolError, "runtime_cancelled"):
                filesystem.search_text(
                    ".",
                    query="needle",
                    max_depth=1,
                    page_size=100,
                    execution_control=_CancelAfter(6),
                )

    def test_listing_classification_joins_exported_entry_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "personal-name.txt"
            secret.write_text("value", encoding="utf-8")

            def classify(observation, provenance):
                return validated_classification(
                    data_class=(
                        "personal_data"
                        if observation.resource_ref == str(secret)
                        else "public"
                    ),
                    provenance=provenance,
                    trust_level="trusted_actor",
                    source_ref=observation.resource_ref,
                    source_revision=observation.resource_revision,
                    source_digest=observation.resource_digest,
                    resource_identity=observation.resource_identity,
                    classification_revision=1,
                )

            result = FullAccessFilesystem(
                workspace_id="default",
                workspace_root=root,
                classification_resolver=classify,
            ).list_entries(
                ".",
                max_depth=1,
                page_size=100,
            )

            self.assertEqual(result.classification.data_class, "personal_data")


if __name__ == "__main__":
    unittest.main()
