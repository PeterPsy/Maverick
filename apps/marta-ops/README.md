# Marta Ops

Marta Ops è il workspace operativo essenziale per il lavoro di Marta Giunti e del suo team.

## Product scope

The app deliberately keeps one central object: a collaboration or piece of work. Each work item connects the partner, current phase, next action, deadline, deliverables, contract state, value, and payment state. A separate lightweight idea inbox captures organic content without turning the app into a second file archive, calendar, mailbox, or accounting system.

The first release has three views:

- **Oggi**: decisions, overdue actions, near deadlines, and money to collect;
- **Lavori**: the active collaboration list and its deliverables;
- **Idee**: quick capture and a tiny selection workflow.

## Owned data

Workspace data is stored under `data/marta-ops/state.json` through the Maverick App SDK storage helpers. The app does not read another app's private data.

## Verify and install

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
maverick app marta-ops frontend build --json
maverick core cli run core.app-sdk.validate --app-id marta-ops --json
maverick core cli run core.app-sdk.register-local --app-id marta-ops --json
maverick core cli run core.app-sdk.install-local --app-id marta-ops --json
maverick core cli run core.app-sdk.status --app-id marta-ops --json
```
