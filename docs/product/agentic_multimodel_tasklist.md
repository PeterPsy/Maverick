# Agentic Multi-Model Runtime — Current Delivery Checklist

Updated: 2026-09-17

## Objective

Provide native Codex and hosted Google/OpenRouter agentic models through direct,
current provider/model configuration without a certification or release-lineage
system. Codex must remain independently usable during hosted-provider changes.

## Delivered

- [x] One current direct definition per runtime/provider/model.
- [x] Direct workspace enable/default, credential, actor and policy binding.
- [x] Minimal session execution binding with no profile/binding revision,
  recipe/catalog/config identity metadata or self-digest.
- [x] Runtime checks limited to real credentials, health, execution mode,
  actor/tool permissions, route and egress.
- [x] Native discovery without catalog expiry; failed refresh retains the last
  usable snapshot.
- [x] Hosted Google and OpenRouter model configs without Full Workspace or
  harness admission contracts.
- [x] Direct Chat and Settings projection without revision grouping or legacy
  selection migration.
- [x] Explicit `runtime_session_restart_required` for incompatible sessions;
  no continuation forks or lineage admission.
- [x] No agentic schema migration during backend bootstrap.
- [x] Contract tests that reject the removed certificate/digest/lifecycle schema.
- [x] Historical event/transcript retention documented as inert data; inactive
  recovery backups are not retained.

## Ongoing validation

- [ ] Run focused provider, runtime-state and recovery tests after runtime
  changes.
- [ ] Run independent Codex and hosted-provider smoke checks after provider or
  catalog changes.
- [ ] Keep Chat, Settings and `/api/providers` direct selection semantics aligned.
- [ ] Expand governed-tool tests when real tool surfaces are added.
- [ ] Keep diagnostics redaction-safe and tied to a real missing dependency or
  denied policy, never to synthetic certification metadata.
