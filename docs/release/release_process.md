# Release Process

Maverick has no stable release yet.

## Versioning

Use semantic versioning after the first public release. Until then, the public open-source branch is pre-release and may change without compatibility guarantees.

## Release Checklist

- unit tests pass
- Python compile check passes
- unused import check passes
- source frontend builds pass
- committed frontend dist policy is verified
- security audit blockers are reviewed
- dependency audit is reviewed
- changelog is updated
- docs and setup instructions are current
- release artifacts have checksums

## Release Notes

Every release note should include:

- user-facing changes
- app contract changes
- runtime and workspace isolation changes
- migration notes
- known security limitations
