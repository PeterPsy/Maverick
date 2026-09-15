"""Bounded deterministic traversal for the full-access filesystem."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path

from core.runtime.full_access_filesystem_support import file_type


@dataclass
class FullAccessFilesystemScanner:
    """Walk host paths breadth-first while enforcing one physical entry limit."""

    max_entries: int
    scanned_entries: int = 0
    truncated: bool = False

    def walk(self, root, *, max_depth, execution_control=None):
        pending = deque([(Path(root), 0)])
        while pending:
            self._check(execution_control)
            current_path, depth = pending.popleft()
            children: list[tuple[dict[str, object], Path]] = []
            try:
                with os.scandir(current_path) as iterator:
                    for child in iterator:
                        self._check(execution_control)
                        if self.scanned_entries >= self.max_entries:
                            self.truncated = True
                            return
                        self.scanned_entries += 1
                        path = Path(child.path)
                        try:
                            info = path.lstat()
                        except OSError:
                            continue
                        kind = file_type(info.st_mode)
                        children.append(
                            (
                                {
                                    "path": str(path),
                                    "name": child.name,
                                    "type": kind,
                                    "depth": depth + 1,
                                    "size_bytes": (
                                        info.st_size if kind == "file" else None
                                    ),
                                },
                                path,
                            )
                        )
            except OSError:
                continue
            children.sort(key=lambda item: str(item[0]["name"]))
            for entry, path in children:
                self._check(execution_control)
                yield entry, path
                if entry["type"] == "directory" and depth + 1 < max_depth:
                    pending.append((path, depth + 1))

    @staticmethod
    def _check(execution_control) -> None:
        if execution_control is not None:
            execution_control.check()


__all__ = ["FullAccessFilesystemScanner"]
