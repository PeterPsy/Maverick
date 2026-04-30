# Maverick App SDK Packaging Guide

Date: 2026-04-21

Package a valid app source tree with:

```bash
scripts/maverick core cli run core.app-sdk.package --app-id my-app --workspace default --json
```

Packaging validates the app contract first.

The SDK writes:

```text
my-app.tar.gz
my-app.tar.gz.manifest.json
```

The manifest includes app identity, version, contract version, distribution metadata, checksum, file list, and packager provenance. Provenance uses workspace-safe source descriptors rather than absolute host paths.

Packages exclude local development junk, runtime state, logs, temp files, and local databases.
