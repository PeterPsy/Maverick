# PWA cache M1 validation — 2026-08-26

This checkpoint records repeatable development evidence for HTTP correctness
and generated frontend assets. It does not replace the physical-device M2
matrix.

## Conditional file response

A temporary loopback WSGI server exercised the real core file-response helper
through `curl` without restarting or changing the shared development backend.

```text
initial GET:       200 OK, ETag "smoke-revision-1", 20 body bytes
conditional GET:  304 Not Modified, same ETag, 0 body bytes
cache policy:      private, no-cache
vary:              Cookie
```

Unit and integration coverage additionally verifies wildcard/list/weak ETags,
strong `If-Range`, ranges and `416`, GET/HEAD parity, authorization before the
precondition, and the prohibition on `304` for `delete_after_send` files.

## Generated assets

The three migrated build manifests were fully re-read and SHA-256 verified by
`core.apps.frontend_assets.load_frontend_asset_manifest(..., verify_files=True)`:

| App | Build id | Immutable | Revalidated |
|---|---|---:|---:|
| Base Shell | `eff9d2a72d27b12fe132eea51262a8d8df163d3531a8d00e7c6c39e56b1a53df` | 3 | 14 |
| App Store | `15f6769b735e633f2570126d2ea8dd289ad61797ce8b710e15792452c35f1485` | 5 | 2 |
| Fitness Coach | `19024c667f5019f17b2c3e89ea3a0fe7478bf199e1d440273878ec1d3444c884` | 11 | 3 |

`npm run test:content-hash` builds a temporary App Store twice, changes exactly
one source byte, and asserts both the emitted filename and digest change. It
also forces a semantic Rollup filename and verifies that the manifest keeps it
in `revalidated`, never `immutable`.

## Design Studio live policy

`python3.13 -m unittest tests.integration.app_hosting.test_sidecar_browser_origin`
ran against a live loopback Design sidecar fixture. A successful
`/_next/static/...` response retained
`private, max-age=31536000, immutable`; documents, APIs, missing assets, and all
other responses retained `no-store`.
