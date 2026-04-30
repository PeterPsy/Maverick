"""Tests for the inline script syntax checker used by hand-authored HTML apps."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


class InlineScriptSyntaxCheckerTest(unittest.TestCase):
    def test_accepts_valid_html_and_rejects_invalid_html(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        checker = repo_root / "scripts" / "check_inline_script_syntax.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid_html = root / "valid.html"
            invalid_html = root / "invalid.html"
            valid_html.write_text(
                "<!doctype html><html><body><script>const ok = 1; console.log(ok);</script></body></html>",
                encoding="utf-8",
            )
            invalid_html.write_text(
                "<!doctype html><html><body><script>const broken = `oops` tail;</script></body></html>",
                encoding="utf-8",
            )

            valid = subprocess.run(
                ["python3", str(checker), str(valid_html)],
                capture_output=True,
                text=True,
                check=False,
            )
            invalid = subprocess.run(
                ["python3", str(checker), str(invalid_html)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(valid.returncode, 0)
        self.assertIn("Validated 1 inline <script> block", valid.stdout)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("failed syntax check", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
