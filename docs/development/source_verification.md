# Source verification

Keep product-build fixtures separate from test fixtures. Builds use the official
isolated `loopino app <id> frontend build --json` surface and an explicitly
selected verification control plane. Tests must not inherit those absolute
control-plane/local-state paths, a service env file, provider credentials or an
operator HOME. Use the installation Node/Python/SQLite toolchains and empty
installation-owned provider homes; tests create their own stores.

The default bounded check is `python scripts/test_suite.py --level fast --jobs 1`.
Run `scripts/check_unused_imports.py` after splits, and retain command, exit status
and full output in ignored operator logs. A retry must identify the failed group
and retain the original result; passing a focused retry does not change the
original command's exit status.

Fake-runner TLS command-flow tests mock only host installation metadata and
declare the supported operator role. Separate unit tests retain executable trust
rejections and non-root managed-exact denial. Real privileged Python startup,
Certbot namespace isolation and installed plugin discovery are explicit operator
checks, not default-fast prerequisites. On a prepared root-operated installation,
run `LOOPINO_OPERATOR_SMOKE=1 .venv/bin/python -m unittest
tests.unit.installation.test_privileged_startup` with the isolated toolchain
environment. This requires the protected installation distribution and mount
namespace capability; an ordinary source checkout does not promise either.

Use a short ignored in-root temporary directory for nested sidecar test
repositories (`/projects/loopino/.t` in this installation). Unix socket names
include workspace/service namespaces and have a kernel length limit. Never
shorten them through an out-of-root fallback or relax the runtime path check.
A snapshot fixture that mutates same-sized file content explicitly advances its
metadata version; it must not depend on two writes getting different clock ticks.
The runtime's metadata fences and assertions remain intact.

Core tests use generic fixtures. Tests that execute actual first-party contracts
or entrypoints belong to the owning app: browser MCP cookie delivery, App Store
display/effect contracts, Calendar/Google app integration and Document Generator
attachment decoding. Shared account and attachment setup lives in `tests/support`;
no test assertions are discarded when moving ownership. Domain fixture modules
keep large test classes within the existing repository ceilings. CLI command
strings such as `apps/sample test` are distinguished from source path literals.
Do not raise ceilings or add exceptions to conceal a failing gate.

Runtime submission diagnostics/timing, child-session construction and policy
reconciliation have explicit modules within the existing service facade. Direct
child-session/policy imports resolve their dependencies without relying on a
previous facade import. Codex turn result/state and prewarm lifecycle retain
existing ownership. These splits do not change authority or execution policy.

After the final app source and mounted frontend builds, verify every declared
frontend file against its manifest. Review admitted read operations before
refreshing exact hosted descriptor/executable pins; retain the fail-closed checks.
Export the approved product selection with `scripts/export_product_catalog.py`
using the real SDK, then verify every package checksum, SDK manifest, metadata,
archive member and packaged source byte. Source verification does not establish
live UI, TLS, provider, confinement or native signing acceptance.
