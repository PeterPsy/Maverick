# Setup And Onboarding UI Plan

Status: full onboarding deferred; provider-first setup exists in `base-shell`.

## Goal

Add a built-in setup or onboarding experience after the CLI-first local setup path is stable.

The current product shell includes one narrow startup setup flow: when the active workspace has no configured runtime provider, `base-shell` prompts an authorized user to select the provider/model through the core provider API. That prompt prevents a fresh install from reaching Chat with a misleading empty provider state.

## Why Deferred

The first public release still needs stronger setup docs, security messaging, ADRs, threat model coverage, and reference docs.

A broad onboarding UI should not become the first bootstrap mechanism before those foundations settle.

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
