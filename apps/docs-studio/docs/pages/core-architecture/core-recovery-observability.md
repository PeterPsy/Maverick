# Recovery and observability

Recovery is not only restarting a process. The platform should know what failed, whether repair is needed first, and what state can be safely resumed.

## Recovery owns

- runtime restart and resume orchestration
- failed-start diagnosis
- health-driven recovery decisions
- backend downtime watchdog escalation
- operator-facing inspection and repair surfaces

## Observability owns

| Signal | Purpose |
| --- | --- |
| Structured events | operational timeline |
| Audit records | governance trail for control-plane changes |
| Runtime logs | provider/process debugging |
| Metrics | supportability and health views |

## Redaction rule

Logs, audit records, and structured events must not leak raw secret values, provider credentials, or sensitive runtime environment payloads.

## Events worth recording

- app registration, install, enable, disable, uninstall, purge
- provider binding, selection, launch, health probe
- runtime session creation and lifecycle transitions
- secret resolution attempts and denials
- recovery intents and action outcomes
