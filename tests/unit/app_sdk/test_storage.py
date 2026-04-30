from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path

from core.app_sdk.storage import read_json_state, update_json_state


def _update_json_key(data_root: str, key: str, value: int) -> None:
    update_json_state(
        Path(data_root),
        "state.json",
        lambda state: {**state, key: value},
        default={},
    )


class AppSdkStorageTestCase(unittest.TestCase):
    def test_update_json_state_keeps_concurrent_read_modify_write_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            processes = [
                multiprocessing.Process(target=_update_json_key, args=(temp_dir, key, value))
                for key, value in (("alpha", 1), ("bravo", 2), ("charlie", 3), ("delta", 4))
            ]

            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)

            self.assertTrue(all(process.exitcode == 0 for process in processes))
            self.assertEqual(
                read_json_state(temp_dir, "state.json"),
                {"alpha": 1, "bravo": 2, "charlie": 3, "delta": 4},
            )


if __name__ == "__main__":
    unittest.main()
