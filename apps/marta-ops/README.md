# Marta Ops

Marta Ops è il workspace operativo essenziale per il lavoro di Marta Giunti e del suo team.

## Product scope

The app deliberately keeps one central object: a collaboration or piece of work. Each work item connects the partner, current phase, next action, deadline, deliverables, contract state, value, and payment state. A separate lightweight idea inbox captures organic content without turning the app into a second file archive, calendar, mailbox, or accounting system.

The first release has three views:

- **Oggi**: decisions, overdue actions, near deadlines, and money to collect;
- **Lavori**: the active collaboration list and its deliverables;
- **Idee**: quick capture and a tiny selection workflow.

## Maverick sidebar

Marta Ops owns the sidebar shown by Maverick while the app is active. It keeps only the three core destinations—Oggi, Lavori, and Idee—and one contextual footer action, **Nuovo lavoro**. Sidebar selection and in-app navigation stay synchronized without reloading the app; on mobile, selecting a destination closes the sidebar.

## Mail and Calendar

An existing work item exposes two deliberately narrow actions:

- **Crea bozza Mail** saves the current work fields and prepares a draft for the partner email. It never sends the message.
- **Aggiungi al Calendario** saves the current work fields and creates an idempotent all-day event for the deadline.

Both integrations use declared optional app interfaces (`mail.workspace` and `calendar.events`) through Maverick's governed dependency backend. Marta Ops never reads Mail or Calendar private data.

## Owned data

Workspace data is stored under `data/marta-ops/state.json` through the Maverick App SDK storage helpers. The app does not read another app's private data.

The CRM extension adds contacts, tasks and an activity timeline to the same atomic JSON envelope (schema 2). Schema 1 work and idea records are retained; missing collections and work ordering/contact fields receive additive defaults in memory, and are persisted only with the next explicit mutation. Bootstrap does not rewrite existing data. Kanban moves use an anchor in the complete destination column, so filtered-out cards retain their relative order. A stale source phase is rejected before any write. Contact archiving retains linked work and tasks.

## Verify and install

```bash
PYTHONPATH=../../../.. python3 -m unittest discover -s tests -p 'test_*.py'
maverick app marta-ops frontend build --json
maverick core cli run core.app-sdk.validate --app-id marta-ops --json
maverick core cli run core.app-sdk.register-local --app-id marta-ops --json
maverick core cli run core.app-sdk.install-local --app-id marta-ops --json
maverick core cli run core.app-sdk.status --app-id marta-ops --json
```
