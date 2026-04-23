# Setup And Onboarding UI Plan

Status: deferred until after the first public open source release checklist is complete.

## Goal

Add a built-in setup or onboarding experience after the CLI-first local setup path is stable.

## Why Deferred

The first public release still needs stronger setup docs, security messaging, ADRs, threat model coverage, and reference docs.

An onboarding UI should not become the first bootstrap mechanism before those foundations settle.

## Intended Scope

The future setup UI should show:

- local host status
- dependency and prerequisite status
- provider readiness
- workspace readiness
- app enablement state
- explicit security warnings

## Non-Goal

The setup UI should not hide unsafe defaults or replace honest documentation about the current experimental status.
