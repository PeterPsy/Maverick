from dataclasses import replace
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.isolation import LabInstallationLayout, directory_identity


class LabIsolationTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = root / 'source'
        self.workspace = self.source / 'workspaces/synthetic'
        self.workspace.mkdir(parents=True)
        (self.source / '.gitignore').write_text('workspaces/\n')
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True, capture_output=True)
        subprocess.run(['git', 'add', '.gitignore'], cwd=self.source, check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.email=offline@example.invalid', '-c', 'user.name=Offline',
                        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'offline source'],
                       cwd=self.source, check=True, capture_output=True)
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.source, check=True, capture_output=True).stdout.decode().strip()
        private = [root / name for name in ('control', 'vault', 'operator', 'active')]
        for path in private:
            path.mkdir(mode=0o700)
        self.layout = LabInstallationLayout('offline-lab', self.source, self.workspace, *private[:3], (private[3],), commit)

    def test_disjoint_source_and_roots_pass_and_replacement_changes_identity(self):
        self.layout.validate()
        before = directory_identity(self.workspace)
        # Keep the old inode alive so this is not an inode-reuse test.
        self.workspace.rename(self.workspace.with_name('old'))
        self.workspace.mkdir()
        self.assertNotEqual(directory_identity(self.workspace), before)

    def test_overlap_alias_shared_git_or_unfrozen_source_denies(self):
        for changes in ({'control_root': self.source}, {'vault_root': self.layout.active_roots[0]},
                        {'operator_root': self.workspace}, {'active_roots': ()}, {'source_commit': 'a' * 40}):
            with self.subTest(changes=changes), self.assertRaises(LabAuthorizationError):
                replace(self.layout, **changes).validate()
        (self.workspace / 'production').symlink_to(self.layout.active_roots[0], target_is_directory=True)
        with self.assertRaisesRegex(LabAuthorizationError, 'alias'):
            self.layout.validate()
        (self.workspace / 'production').unlink()
        (self.source / '.gitignore').write_text('tampered')
        with self.assertRaisesRegex(LabAuthorizationError, 'not_frozen'):
            self.layout.validate()

    def test_hardlinks_and_git_alternates_are_not_separate_installations(self):
        secret = self.layout.active_roots[0] / 'marker'
        secret.write_text('synthetic non-secret sentinel')
        os.link(secret, self.workspace / 'alias')
        with self.assertRaisesRegex(LabAuthorizationError, 'alias'):
            self.layout.validate()
        (self.workspace / 'alias').unlink()
        alternate = self.source / '.git/objects/info/alternates'
        alternate.write_text(str(self.layout.active_roots[0]))
        with self.assertRaisesRegex(LabAuthorizationError, 'not_independent'):
            self.layout.validate()


if __name__ == '__main__':
    unittest.main()
