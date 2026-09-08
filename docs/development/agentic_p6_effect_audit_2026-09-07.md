# P6 Design Studio effect-audit extension — 2026-09-07

Scope: source-level renewal of the Design Studio **CLI** executable-closure
digest after commit `e5e6ec2e`; this is not provider certification, remote-data
classification, egress approval, or a release decision.

The descriptor and declared effects did not change. The sole executable-closure
delta is `service/official_update_lock.py`, which now permits an inactive lock
inode created by another member of the explicitly trusted setgid operating
group to be handed to the current service process.

The reviewed path remains fail closed:

- the stale object must be a regular, single-link inode;
- the parent must be a setgid, group-writable and group-searchable directory;
- file and directory group ids must match a current effective or supplementary
  group;
- the old inode is exclusively locked and rechecked by device, inode and
  ctime before replacement;
- replacement uses a newly created `0600`, single-link, current-user inode,
  atomically installs it, rechecks it and fsyncs the directory;
- symlinks, ownership/group mismatches, concurrent path changes and lock
  contention fail closed.

The existing Design Studio regressions exercise ordinary locking, permission
repair, inactive shared-group handoff, concurrent ownership and path-change
rejection. The certification corpus additionally recomputes the complete
built-in descriptor and executable-closure inventory; any later byte drift
invalidates the authority.

Audit revision `2026-09-07-p6-builtin-effects-reviewed-v5` changes only the
Design Studio CLI execution digest from
`c82389092a0cc269ffb98eb7bccf61009bc6f16628ffae2215d0f29e5d32ae13` to
`5cf1239dfe1d9938d32f9dd19a9506a5a1e1e41c56ff4a3e32b8093787b4291a`.
No content is thereby declared public or safe for provider egress.
