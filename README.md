# Default workspace

Shared app source and all project development history are consolidated in the
Maverick root repository on `design`:

```text
/home/ubuntu/projects/maverick-v3
```

GitHub Actions and Marta Ops use installation-level source under root `apps/`.
The default workspace retains its app data, Storage files, and runtime material;
these are excluded from source Git and must be transferred separately for a
server move. This workspace no longer owns an independent app repository.

Follow the root `AGENTS.md` and
`docs/development/design_consolidation_2026-10-14.md` for source ownership and
the retained development histories.
