"""Tests for trusted local operating-group handoffs."""

from __future__ import annotations

import stat
from types import SimpleNamespace
import unittest

from core.shared.operating_group import permits_operating_group_handoff


class OperatingGroupTests(unittest.TestCase):
    def test_accepts_single_link_regular_file_in_shared_setgid_directory(self) -> None:
        self.assertTrue(
            permits_operating_group_handoff(
                _metadata(stat.S_IFREG | 0o660, gid=42),
                _metadata(stat.S_IFDIR | stat.S_ISGID | 0o770, gid=42),
                effective_gid=7,
                supplementary_gids=(42,),
            )
        )

    def test_rejects_untrusted_or_ambiguous_handoffs(self) -> None:
        shared = _metadata(stat.S_IFDIR | stat.S_ISGID | 0o770, gid=42)
        for candidate, directory, groups in (
            (_metadata(stat.S_IFLNK | 0o770, gid=42), shared, (42,)),
            (_metadata(stat.S_IFREG | 0o660, gid=42, nlink=2), shared, (42,)),
            (_metadata(stat.S_IFREG | 0o660, gid=99), shared, (42,)),
            (_metadata(stat.S_IFREG | 0o660, gid=42), shared, (7,)),
            (
                _metadata(stat.S_IFREG | 0o660, gid=42),
                _metadata(stat.S_IFDIR | 0o770, gid=42),
                (42,),
            ),
        ):
            with self.subTest(candidate=candidate, directory=directory, groups=groups):
                self.assertFalse(
                    permits_operating_group_handoff(
                        candidate,
                        directory,
                        effective_gid=7,
                        supplementary_gids=groups,
                    )
                )


def _metadata(mode: int, *, gid: int, nlink: int = 1):
    return SimpleNamespace(st_mode=mode, st_gid=gid, st_nlink=nlink)


if __name__ == "__main__":
    unittest.main()
