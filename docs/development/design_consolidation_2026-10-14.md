# Design repository consolidation

Date: 2026-10-14

## Source ownership

All first-party source for this installation belongs to the Maverick repository
on `design`. GitHub Actions and Marta Ops were promoted through the authenticated
App Store from `workspaces/default/apps/` to root `apps/`. Both are
`source_available` / `forkable` platform sources. CRM, Mail, and the other shared
apps already live in the root repository.

The old workspace Git repository is retired after its complete history is
imported into `design`. `workspaces/default/` remains a tenant directory for
business data, Storage files, and runtime material, excluded from source Git.
Future workspace-local forks remain an explicit platform capability, rather
than a second development repository for these shared apps.

Marta Ops now resolves the shared PWA package and Vite plugins from its root-app
location. Its committed frontend is rebuilt through the platform build surface.
App Store management dialogs were also raised above the carousel: the former
stacking order prevented mouse interaction with promotion confirmations.

## Runtime migration

Promotion registers the new platform source but intentionally keeps the local
project. Complete local-project removal deletes its app-owned data, so the
existing data directories were temporarily moved inside the workspace before
the official removal operation, restored immediately, and attached through the
official platform installation operation. The temporary migration directories
were removed after restoration.

The app ids and data namespaces are unchanged. Business-data file hashes were
compared before and after migration; only platform installation metadata may
change. Marta Ops retains its Mail, Calendar, and Storage dependency selections.
No control-plane collections or secret values were edited directly.

Fusion Connector was removed through its complete-removal surface. Its source,
binding, project registration, and app data were deleted. Its persistent skill
was deleted through Skills, and 157 generated runtime skill copies were removed.
Historical source and audit records remain historical records; Git history is
not rewritten.

## Historical branches

The consolidation merge retains audited branch histories with the `ours`
strategy. The current production tree remains authoritative; this is archival
ancestry, rather than adoption of superseded implementations.

| Previous branch | Disposition |
| --- | --- |
| `main` (`9919bb3c`) | Separate April history, without a common ancestor with `design`; preserve history without restoring the old platform. |
| `agent/design-studio-review-findings` (`3933d3b7`) | August overlay/artifact implementation superseded by the native OpenDesign cutover, including `1458fae1`. |
| `codex/installation-setup` (`8f52f423`) | All three branch-only patches have equivalents in `design`. |
| `fix/login-session-recovery-20261001` (`c68a180f`) | Incorporated and hardened by `1bb384fe`; renewal, shell confirmation, and regression tests remain in the production tree. |
| `p6/*-20260906` | Earlier certification candidates; the certificate lifecycle was explicitly removed by `060b48c9` on 2026-09-14. Preserve evidence without restoring that subsystem. |
| `video-studio/*` | Video Studio was explicitly removed by `036ccdf1` on 2026-09-19. Preserve history without reinstalling it. |
| Remaining local branches and detached worktree heads | Already reachable from `design`, or retained by the archival merge. |
| Former workspace `main` | Preserve the complete app-development history, including the retirement commits, under `design`. |

Before removing branch refs or worktrees, verify that every recorded original
head is an ancestor of the final `design` head. Remove linked checkouts only
after verifying their tracked files are clean and no process uses their cwd.
The Installation worktree's four untracked entries are dependency symlinks;
unlink the symlinks without deleting their targets. Prune the 26 registrations
whose source directories no longer exist.

## Verification

- Browser TLS: 13 unit tests and 2 integration tests pass.
- Official SDK validation passes for both promoted root app sources.
- GitHub Actions: 5 backend tests pass.
- Marta Ops: 24 backend tests and 39 frontend tests pass.
- App Store fast checks pass: 55 discovered, with 42 integration checks skipped.
- The App Store and Marta Ops official frontend builds pass.
- Promotion succeeds through the mounted App Store after the dialog repair.
- Business-data hashes and governed dependency selections are preserved.
- The final source delta and Git whitespace checks pass.
- All 2,286 repository-owned Python files pass the unused-import check.
- Mounted Marta Ops renders without an alert; the App Store renders at a
  390 x 844 mobile viewport without an alert.

## Final repository state

The archival merge is `03655258`. All 48 distinct original branch/worktree
heads are ancestors of `design`, and the merge leaves the production tree
unchanged. The complete reference inventory and migration results are retained
in [`design_consolidation_refs_2026-10-14.json`](design_consolidation_refs_2026-10-14.json).

Only the root checkout and the local `design` branch remain. Five linked
checkouts were removed, 26 obsolete registrations were pruned, and 23 redundant
local branch refs were retired after ancestry verification. The nested
workspace `.git` directory is removed, so Git operations from the default
workspace resolve to the same root `design` repository. Nine remote-tracking
refs for deleted Dependabot branches were pruned through an ordinary fetch.
Two uninstalled app directories contained only Python caches and were removed.

The imported backend's extra EOF line was removed in a corrective checkpoint.
Generated frontend bundles contain intentional whitespace inside upstream CSS
template strings; `.gitattributes` excludes only end-of-line whitespace for
committed `frontend/dist` files while retaining ordinary source checks. Bundle
content remains the official build output, including its asset manifest.

The repository-wide unused-import scan also scans ignored downloaded source.
It reports four existing imports inside the untracked OpenWA upstream SDK;
that external checkout is not modified by this consolidation. Verification of
repository-owned Python source must exclude downloaded, untracked dependencies.

For a server move, transfer the installation's durable control-plane state,
secret key material, and workspace data separately from the source checkout.
Those are operational data, not source commits.
