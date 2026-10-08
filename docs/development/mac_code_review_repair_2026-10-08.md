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

Installation run `37755999882` completed successfully at the exact native commit
above, with `install_and_open=true`. The log confirms the atomic update at the
existing path, signature continuity and `Installed and running: 0.2.2 (53)` at
09:22:21 UTC. This run repeated all 278 Swift tests and seven signed native cases
without failures. No second dispatch was needed.

Backend restart completed at 09:22:31 UTC. The ordinary restart CLI could not
reach systemd from its mount namespace; the user-authorized host-namespace
systemctl operation restarted `maverick-core.service`. Subsequent inspection
confirmed PID 1016581 (previously 945651), active/running state and `/health`
returning `{"status":"ok","service":"maverick-core"}`.

After installation/restart, this chat's direct native calls returned
`Device Use executor is unavailable`. No native input was replayed. Installation
and launch are verified from the signed runner, but a fresh live chat-to-Mac
end-to-end picker test remains unverified until PC use is reconnected. This is
separate from the tested operation-timeout and cross-turn activation fixes.
