# Maverick PWA Offline-Aware Product Contract

Status: approved for M0 on 2026-08-26. This document controls product copy and
the global connection-state UI used by Base Shell.

## Approved positioning

Use this sentence in Italian product surfaces:

> Maverick è offline-aware e supporta consultazione e preparazione locale
> selettiva; l'esecuzione agentica richiede la rete.

English equivalent:

> Maverick is offline-aware and supports selective local review and
> preparation; agentic execution requires a network connection.

Do not describe Maverick as generally “offline capable”, “fully offline”, or
able to run models, agents, providers, or tools offline.

## Capability matrix

| Capability | M2 | Later opt-in milestones | Never authorized by local cache |
|---|---:|---:|---:|
| Reopen branding and Base Shell | yes | yes | — |
| Inspect local-content status and last sync | yes | yes | — |
| Open an app frame without network | explicit unavailable state | static app shell where verified | — |
| Read a private read model after cold offline restart | no | only reviewed, scoped resources | — |
| Open a Storage file selected as Available Offline | no | M4 | — |
| Prepare a local draft | no | selected later resources | — |
| Submit a prompt or remote mutation | no | only after reconnect and server checks | yes |
| Run a model, agent, provider, tool, or egress | no | no | yes |
| Decide capability, admission, authority, confirmation, or revocation | no | no | yes |

## Single global indicator

There is exactly one global Offline indicator. It occupies the slot that would
otherwise show the current app icon in the top-left sidebar.

Expanded state:

```text
┌──────────────────────────────────┐
│ [cloud_off  Offline]  Workspace  │  <- current-app icon slot
│ Ultima sincronizzazione: 14:32   │
│                                  │
│ Contenuti sul dispositivo        │
└──────────────────────────────────┘
```

Rail-only state:

```text
┌──────┐
│  !   │  accessible name: “Offline — apri contenuti sul dispositivo”
├──────┤
│ app  │
│ app  │
└──────┘
```

The indicator cannot rely on color alone. In the expanded state it says
**Offline**. In the compressed state it has an icon plus an accessible name and
tooltip. Activating either state opens the same local-content management view.

No second global banner may appear above an iframe, in an app header, in the
main work area, or as a persistent toast. An app may show an inline explanation
beside content or an action that specifically needs the network.

## Connection state

The shell may move to Offline immediately after a browser `offline` event or a
failed bounded Maverick probe. A browser `online` event means only “checking”.
The app icon returns after a fresh same-origin Maverick request succeeds.

The component exposes:

- current state (`Offline` or update state);
- last successful Maverick synchronization time;
- source (`Rete` or `Dispositivo`);
- freshness (`Aggiornato`, `Non verificato`, or `Scaduto`);
- sync state (`Inattivo`, `Aggiornamento`, `Offline`, or `Errore`).

## Online-only actions

While Offline, Base Shell prevents interaction with mounted app frames unless a
later app explicitly implements an approved offline surface. The contextual
state explains that remote actions require a connection and directs the user
to local-content management. This ensures that a prompt, model, agent, tool, or
mutation does not merely look actionable and then fail ambiguously.

## Private content rule for M2

M2 persists no private app read model. A cold offline launch displays only the
static shell, public branding, connection status, and local-content management
surface. It does not infer authorization from an old iframe, app registry
snapshot, session cookie, local preference, or cached control-plane response.
