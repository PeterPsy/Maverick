"""Native Codex resolution for valid npm dependency layouts."""

from pathlib import Path
import tempfile
import unittest

from core.providers.provider_codex_runtime import CodexProviderAdapter


class CodexBinaryResolutionTest(unittest.TestCase):
    def test_npm_layouts_launch_the_native_binary_inside_the_sandbox(self):
        for hoisted in (False, True):
            with self.subTest(hoisted=hoisted), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                scope = root / "node_modules/@openai"
                package = scope / "codex"
                entrypoint = package / "bin/codex.js"
                entrypoint.parent.mkdir(parents=True)
                entrypoint.write_text("#!/usr/bin/env node\n")
                dependencies = scope if hoisted else package / "node_modules/@openai"
                binary = dependencies / "codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"native-test-binary")
                adapter = CodexProviderAdapter(codex_command=str(entrypoint))
                command = adapter._runtime_command(str(entrypoint))
                self.assertEqual(command, str(binary))
                launch = adapter._build_command(
                    workspace_root=root / "workspace",
                    runtime_root=root / "runtime",
                    runtime_home=root / "runtime/codex-home",
                    execution_mode="sandbox",
                    host_command=command,
                )
                self.assertIn("--dependency-file", launch)
                self.assertIn(
                    f"{binary}={root / 'runtime/bin/codex'}", launch,
                )
                self.assertEqual(launch[launch.index("--") + 1], str(root / "runtime/bin/codex"))

    def test_nested_dependency_takes_precedence_over_hoisted_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            scope = Path(temp) / "node_modules/@openai"
            package = scope / "codex"
            entrypoint = package / "bin/codex.js"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("#!/usr/bin/env node\n")
            binaries = []
            for parent in (package / "node_modules/@openai", scope):
                binary = parent / "codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"native-test-binary")
                binaries.append(binary)
            adapter = CodexProviderAdapter(codex_command=str(entrypoint))
            self.assertEqual(adapter._runtime_command(str(entrypoint)), str(binaries[0]))
