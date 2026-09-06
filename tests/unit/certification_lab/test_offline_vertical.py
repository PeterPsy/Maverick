"""Frozen-source private bootstrap and natural hosted loop, offline HTTP only."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from core.certification_lab.bootstrap import lab_process_environment
from core.certification_lab.isolation import LabInstallationLayout


class LabOfflineVerticalTest(unittest.TestCase):
    def test_real_private_worker_nested_edit_test_and_revocation(self):
        original = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix='maverick-lab-offline-') as name:
            root = Path(name)
            source = root / 'source'
            source.mkdir()
            names = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=original,
                                    check=True, capture_output=True).stdout.decode().split('\0')
            for relative in set(names) - {''}:
                path = original / relative
                if not path.is_file():
                    continue
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                target.chmod(path.stat().st_mode & 0o777)
            subprocess.run(['git', 'init', '-q', str(source)], check=True, capture_output=True)
            subprocess.run(['git', 'add', '-A'], cwd=source, check=True, capture_output=True)
            subprocess.run(['git', '-c', 'user.email=offline@example.invalid', '-c', 'user.name=Offline',
                            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'frozen offline candidate'],
                           cwd=source, check=True, capture_output=True)
            commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, check=True, capture_output=True).stdout.decode().strip()
            workspace = source / 'workspaces/synthetic'
            workspace.mkdir(parents=True)
            for part in ('control', 'vault', 'operator', 'active'):
                (root / part).mkdir(mode=0o700)
            layout = LabInstallationLayout('offline-lab', source, workspace, root / 'control', root / 'vault', root / 'operator', (root / 'active',), commit)
            config = root / 'operator/config.json'
            config.write_text(json.dumps({'installation_id': layout.installation_id, 'source': str(source), 'workspace': str(workspace),
                'control': str(layout.control_root), 'vault': str(layout.vault_root), 'operator': str(layout.operator_root),
                'active_roots': [str(p) for p in layout.active_roots], 'source_commit': commit}))
            result = subprocess.run([sys.executable, '-m', 'tests.support.lab_offline_vertical', str(config)],
                                    cwd=source, env=lab_process_environment(layout), capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr.decode() + result.stdout.decode())
            payload = json.loads(result.stdout)
            self.assertEqual(payload['generations'], 5)
            self.assertEqual(payload['certificate_count'], 0)
            self.assertEqual(payload['remaining_processes'], 0)
            self.assertGreater(payload['artifacts'], 10)
            self.assertEqual(payload['authority_domain'], 'certification_lab')
            self.assertEqual(list((root / 'active').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
