# ADR-0006: MIT Licensing Choice

## Status

Accepted

## Context

The repository needs an unambiguous, permissive, and widely understood open source license for a first public release.

## Decision

- Maverick uses the MIT License at the repository root
- app package metadata and Python package metadata should align to MIT
- `"private": true` in app package metadata means "not published to npm", not "not open source"

## Consequences

- legal permissions are easy to understand quickly
- contributors and reviewers do not have to infer the licensing intent from mixed metadata
