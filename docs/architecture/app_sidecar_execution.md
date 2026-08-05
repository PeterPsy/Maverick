# Confined Execution For App-Owned Sidecars

Date: 2026-08-03
Status: Accepted and implemented for the generic WP1 boundary
Owners: Maverick Core app hosting and app contract domains

## Context

A loopback bind is not a sandbox. A compromised sidecar on the host network can
probe core, metadata services, other local daemons, and the internet; a process
started from `dict(os.environ)` also receives operator paths and unrelated
credentials. App-owned sidecars therefore need a generic, fail-closed execution
boundary before sandbox-compatible apps may rely on them.

## Decision

On Linux, a sandbox-required HTTP sidecar runs beneath a core-owned bubblewrap
launcher. The contract declares generic process policy equivalent to:

```json
{
  "inherit_host_env": false,
  "sandbox": "required",
  "bundle_read_only": true,
  "workspace_data_write": true,
  "network": "isolated",
  "transport": "unix_relay",
  "outbound": [],
  "limits": {
    "memory_bytes": 4294967296,
    "open_files": 1024,
    "request_concurrency": 32
  }
}
```

Names may follow existing contract conventions, but these semantics do not
weaken. A sandbox-only workspace cannot start the sidecar if bubblewrap, user or
network namespaces, mount policy, or relay creation fails. There is no fallback
to an unsandboxed process or host loopback.

## Filesystem And Environment

The launcher starts from an empty environment. Core adds only a fixed minimal
runtime `PATH`, locale/timezone values when required, contract-declared values,
and substitutions for the active app data generation, isolated temporary
directory, internal bind address/port, and technical authentication. It does
not inherit `HOME`, provider/runtime homes, secret-store keys, bootstrap
secrets, platform cookies, provider credentials, or unrelated host variables.

The production WP1 mount table exposes:

- the resolved app source and minimal runtime closure read-only; WP5 replaces
  the source mount with the verified artifact;
- only the validated app-owned `data_root` supplied by the lifecycle resolver
  read/write; WP6 narrows Design Studio's value to the active
  `opendesign/instances/<generation>/data` subtree;
- a dedicated temporary `tmpfs` read/write;
- a dedicated relay socket directory, with no general host path semantics;
- the minimum runtime libraries and pseudo-filesystems required to execute.

Operator home, control-plane stores, Storage roots, other app data, other
workspaces, inactive generations, and arbitrary host paths are absent. Bundle
writes and any write outside the active data/temp/relay roots fail. Browser
input never selects a mount source or host path.

## Network And Relay

The sidecar receives a new network namespace with only its internal loopback.
There is no default route and no direct egress. Host loopback is not visible.
Core reaches the sidecar through a core-owned relay in that namespace: the relay
creates a Unix-domain socket in the dedicated mounted socket directory and
forwards only to the sidecar's internal loopback listener. The host never
publishes the internal TCP port.

Each socket is bound to workspace, local app id, sidecar id, and resolved data
root in the core registry; WP6 makes the data root a generation identity. Its
directory is `0700`, the socket is `0600`, and every connection must first
present an ephemeral relay capability supplied to the relay over an inherited
file descriptor. The relay strips that preamble before forwarding. Requests
still require the distinct internal HTTP technical token and route policy. A
socket from another workspace, process without the relay capability, or stale
data-root identity is rejected, and lifecycle cleanup unlinks the socket.

No generic TCP/HTTP CONNECT proxy is mounted. Any future outbound operation
must use a separately declared Maverick broker. If G3 selects A-ACP, only the
curated runtime shim receives a distinct per-run Unix broker socket; it is not
available to the OpenDesign daemon generally and cannot reach arbitrary
destinations.

## App Entrypoint Broker

The relay above is sidecar transport and is never delivered to app code. When
an app contract declares `entrypoint_access`, core creates a second temporary
Unix socket for exactly one backend, CLI, MCP, or reference invocation. The
app-facing socket terminates a small core-owned JSON broker; it is not a general
network proxy and cannot choose a host, workspace, app, service, or sidecar
technical listener.

Each declared service receives a separate random capability. Core retains only
its SHA-256 digest and binds it to the invocation correlation id, workspace,
local app id, service id, trusted surface, actor, exact route allowlist, TTL of
at most 30 seconds, request budget, and body bounds. The broker reuses the
confined relay internally, so the app never receives the internal port,
technical HTTP token, relay preamble, sidecar data path, or another workspace's
socket. The private directory is `0700`, its socket is `0600`, and both are
removed after atomic revocation at entrypoint completion. Expiry, revocation,
scope mismatch, noncanonical paths, disallowed routes, budget exhaustion, and
oversized bodies fail without a direct fallback.

This capability closes only app-to-own-sidecar transport. It does not sandbox
the app backend subprocess itself; that broader production blocker remains
listed in `SECURITY.md` and `docs/security/production_readiness.md`.

## Process Lifecycle And Limits

Core owns one process group for bubblewrap, relay, sidecar, and descendants.
Shutdown, timeout, app disable, workspace close, generation cutover, and failed
health checks terminate the entire group, wait a bounded grace period, then
kill remaining descendants. The relay and sockets are removed only after the
group exits.

The health declaration bounds startup. `process_policy.limits` bounds concurrent
requests independently at the core proxy and relay, plus address space and open
file descriptors. The relay applies the OS limits before it starts the app
daemon so descendants inherit them. The
root mount is read-only; only `/data`, the private relay directory, `/tmp`, and
required pseudo-filesystems are separate writable mounts. Future aggregate
disk/process-count controls require a supported host quota/cgroup primitive and
must fail closed when declared; WP1 does not pretend `RLIMIT_NPROC` is a
per-sidecar bound on hosts where it is actually per-user.

## Ownership

Core parses and serializes the generic process policy, resolves verified paths,
constructs the empty environment and bubblewrap command, owns relay identity,
starts/terminates the group, applies resource limits, and audits lifecycle and
denials. Apps declare needs but cannot supply bubblewrap flags, mount sources,
host network destinations, Unix socket paths, uid/gid, or fallback commands.

## Proof

Run the decision proof and the production-path integration suite:

```bash
python3 -m unittest tests.architecture.test_sidecar_confinement_proof
python3 -W error::ResourceWarning -m unittest \
  tests.integration.app_hosting.test_sidecar_execution
```

Both suites use the installed bubblewrap binary and a real network namespace. They
show that a host sentinel and `HOME` are absent, the app source mount is
read-only, only the active data root is writable, operator-home and another
workspace are absent, no default network route exists, host loopback and an
internet address are unreachable, and core can reach the internal health
listener only through a mode-`0600` Unix relay. It also starts a descendant and
verifies that terminating the wrapper leaves no orphan. The production suite also
exercises the actual contract parser, allowlisted environment, bubblewrap launch
plan, authenticated Unix HTTP relay, request semaphore, lifecycle callback, and
mode cleanup. A missing bubblewrap path and an absolute app command are rejected
explicitly before launch.

Expected result: all tests pass on a supported Linux host. Failure to create a
namespace is a failed gate, not a skip.

## Implementation And Residual Closure

- WP1 implements the generic contract, strict serializer/store round trip,
  empty environment, bubblewrap launcher, authenticated Unix relay, group
  lifecycle, address-space/file-descriptor/request limits, and hostile suite.
- WP5 verifies the read-only artifact and native runtime closure used by the
  launcher.
- WP6 binds every launch and relay to the active artifact/data generation.
- WP7 mounts a distinct runtime broker socket only if the selected bridge needs
  it.
- WP10 repeats filesystem/network/workspace A/B, timeout, restart, and orphan
  cleanup tests against the production launcher. Design Studio's official OCI
  browser proof and stable evidence map now close this item.

The OpenDesign-specific launcher remains app-owned. Core contains no
OpenDesign-specific command, route, environment key, mount path, or fallback.
