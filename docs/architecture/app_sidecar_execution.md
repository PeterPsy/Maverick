# Confined Execution For App-Owned Sidecars

Date: 2026-08-03
Status: Accepted (G2)
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
  "outbound": []
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

The mount table exposes:

- the verified artifact/runtime closure read-only;
- only the active `data/<local_app_id>/opendesign/instances/<generation>/data`
  subtree read/write;
- a dedicated bounded temporary filesystem read/write;
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

Each socket is bound to workspace, local app id, sidecar id, and generation in
the core registry. Its directory and socket use the narrow service identity and
mode `0600` (or a platform-equivalent ACL). Requests still require the internal
technical token and route policy. A socket from another workspace, identity, or
generation is rejected and stale sockets are unlinked during lifecycle cleanup.

No generic TCP/HTTP CONNECT proxy is mounted. Any future outbound operation
must use a separately declared Maverick broker. If G3 selects A-ACP, only the
curated runtime shim receives a distinct per-run Unix broker socket; it is not
available to the OpenDesign daemon generally and cannot reach arbitrary
destinations.

## Process Lifecycle And Limits

Core owns one process group for bubblewrap, relay, sidecar, and descendants.
Shutdown, timeout, app disable, workspace close, generation cutover, and failed
health checks terminate the entire group, wait a bounded grace period, then
kill remaining descendants. The relay and sockets are removed only after the
group exits.

The policy declares bounded startup/health time, request concurrency, response
and request sizes, memory/address-space ceilings when the host supports them,
file descriptors, process count, and temporary storage. Unsupported mandatory
limits make a sandbox-required launch fail; they are not silently ignored.

## Ownership

Core parses and serializes the generic process policy, resolves verified paths,
constructs the empty environment and bubblewrap command, owns relay identity,
starts/terminates the group, applies resource limits, and audits lifecycle and
denials. Apps declare needs but cannot supply bubblewrap flags, mount sources,
host network destinations, Unix socket paths, uid/gid, or fallback commands.

## Proof

Run:

```bash
python3 -m unittest tests.architecture.test_sidecar_confinement_proof
```

The proof uses the installed bubblewrap binary and a real network namespace. It
shows that a host sentinel and `HOME` are absent, the artifact mount is
read-only, only the active data root is writable, operator-home and another
workspace are absent, no default network route exists, host loopback and an
internet address are unreachable, and core can reach the internal health
listener only through a mode-`0600` Unix relay. It also starts a descendant and
verifies that terminating the wrapper leaves no orphan. A missing bubblewrap
path is rejected explicitly by the proof launcher helper.

Expected result: all tests pass on a supported Linux host. Failure to create a
namespace is a failed gate, not a skip.

## Residual Risk And Closure

- WP1 implements this policy in the generic contract, launcher, relay, process
  registry, audit, resource limits, and hostile integration suite.
- WP5 verifies the read-only artifact and native runtime closure used by the
  launcher.
- WP6 binds every launch and relay to the active artifact/data generation.
- WP7 mounts a distinct runtime broker socket only if the selected bridge needs
  it.
- WP10 repeats filesystem/network/workspace A/B, timeout, restart, and orphan
  cleanup tests against the production launcher.

Until WP1 passes, a sandbox-required sidecar must not claim confinement based
only on loopback binding.
