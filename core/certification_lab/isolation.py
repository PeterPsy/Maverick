"""Pre-bootstrap installation separation, without invoking platform bootstrap."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.permit import require_digest, require_id


@dataclass(frozen=True)
class LabInstallationLayout:
    installation_id: str
    repository_root: Path
    workspace_root: Path
    control_root: Path
    vault_root: Path
    operator_root: Path
    active_roots: tuple[Path, ...]
    source_commit: str

    def validate(self) -> None:
        """Must run before *each* bootstrap, and be rechecked by live authority."""
        require_id(self.installation_id)
        require_digest(self.source_commit, length=40)
        lab = (self.repository_root, self.workspace_root, self.control_root, self.vault_root, self.operator_root)
        if not self.active_roots:
            raise LabAuthorizationError("lab_active_installation_required")
        try:
            all_paths = (*lab, *self.active_roots)
            for path in all_paths:
                if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
                    raise LabAuthorizationError("lab_installation_alias")
            for candidate in lab:
                for active in self.active_roots:
                    _require_disjoint(candidate, active)
            # Runtime persistence needs repository/workspaces/<id>. All other
            # control material is outside the entire source/tenant tree.
            if self.workspace_root.parent != self.repository_root / "workspaces":
                raise LabAuthorizationError("lab_workspace_layout_invalid")
            for index, private in enumerate(lab[2:]):
                _require_disjoint(private, self.repository_root)
                for other in lab[2:][index + 1:]:
                    _require_disjoint(private, other)
                info = private.stat()
                if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                    raise LabAuthorizationError("lab_private_store_unavailable")
            # A Git worktree/alternates can still read or mutate active Git
            # administration despite an apparently separate source path.
            git_dir = self.repository_root / ".git"
            if not git_dir.is_dir() or git_dir.is_symlink() or (git_dir / "objects/info/alternates").exists():
                raise LabAuthorizationError("lab_source_not_independent")
            for private in lab:
                _reject_alias_entries(private)
            for active in self.active_roots:
                _require_disjoint(git_dir, active)
            environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.operator_root),
                           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
            result = subprocess.run(
                ["/usr/bin/git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "rev-parse", "HEAD"],
                cwd=self.repository_root, env=environment, capture_output=True, timeout=10, check=True,
            )
            if result.stdout.decode().strip() != self.source_commit:
                raise LabAuthorizationError("lab_source_commit_mismatch")
            result = subprocess.run(
                ["/usr/bin/git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "status", "--porcelain", "--untracked-files=normal"],
                cwd=self.repository_root, env=environment, capture_output=True, timeout=10, check=True,
            )
            if result.stdout:
                raise LabAuthorizationError("lab_source_not_frozen")
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            raise LabAuthorizationError("lab_installation_unavailable") from error


def directory_identity(path: Path) -> str:
    """Bind the exact root inode, not just a path which can be replaced."""
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError
        content = json.dumps({"path": str(path), "device": info.st_dev, "inode": info.st_ino}, sort_keys=True).encode()
        return hashlib.sha256(content).hexdigest()
    except (OSError, ValueError) as error:
        raise LabAuthorizationError("lab_root_identity_invalid") from error


def _require_disjoint(left: Path, right: Path):
    if left.is_relative_to(right) or right.is_relative_to(left) or left.samefile(right):
        raise LabAuthorizationError("lab_installation_overlap")


def _reject_alias_entries(root):
    # Do not follow symlinks. Reject sockets/devices/hardlinks and every linked
    # descendant rather than trusting an allowlist of convenient source aliases.
    # Private node_modules should be installed/copied only after this source
    # boundary is sealed, never inherited from the active installation.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode)
                    and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                raise LabAuthorizationError("lab_installation_alias")
