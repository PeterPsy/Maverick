# Mac coding review repair — 2026-10-08

Backend commit: `89826df0` (`design`, pushed).
Native commit: `f3d953b4bbacd0cc075eadd4bddc0b116b313b6d`
(`giuntiocram/maverick-glasses-ios`, `maverick-integration`, pushed).

The paired v49 change fixes cancellation before filesystem commit, process UTF-8
pagination, complete directory pagination and stale reconnection test contracts.
Full timeouts cancel one native operation while retaining the activation; Core
fences new work until settlement and validates/discards late text/images without
replay. The native executor enforces its own deadline.

Validation: 39 Device Use tests and 47 API/provider tests passed. Script tests:
43 passed and one skipped on Linux. Unused-import and diff checks passed.
Native build run `37755584889` succeeded: 278 Swift tests, seven signed native
background-input cases, release build, pinned signature and identity continuity.

Installation run `37755999882` was dispatched once with `install_and_open=true`,
at the exact native commit above. It is still in progress; do not infer install
success or redispatch without inspecting that run. Target version: 0.2.2 (53).

Backend deployment is pending. The ordinary restart CLI returned
`restarted=false` because its mount namespace lacks the host's systemd socket.
Read-only host-namespace inspection via `sudo -n nsenter --target 1 --mount`
confirmed `maverick-core.service` is active with `Restart=always`, PID 945651.
The user explicitly authorized a necessary backend restart. Use host systemd to
restart that service and verify a changed PID, active state and `/health`.
The service owns this agent's cgroup, so restart can interrupt this turn; resume
from these recorded run IDs and current state. The Mac connection must be
observed anew; never replay any native invocation.
