import json
import os
import subprocess
import unittest

from support import APP_ROOT
from external_apps.policy import HEADERS


@unittest.skipUnless(os.environ.get("EXTERNAL_APPS_BROWSER_TEST") == "1", "opt-in real public browser proof")
class PublicBrowserTests(unittest.TestCase):
    def test_esm_lazy_chunks_and_spa_routing_work_but_cookie_tossing_and_storage_do_not(self):
        result = subprocess.run(["node", str(APP_ROOT / "tests/browser_sandbox.cjs")],
                                input=json.dumps(HEADERS), text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
