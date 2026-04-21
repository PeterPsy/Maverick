# Maverick App SDK Packaging Guide

Date: 2026-04-21

Package a valid app source tree with:

```bash
scripts/maverick app package --app-root workspaces/default/apps/my-app
```

Packaging validates the app contract first.

The SDK writes:

```text
my-app-0.1.0.tar.gz
my-app-0.1.0.tar.gz.manifest.json
```

The manifest includes app identity, version, contract version, distribution metadata, checksum, file list, and packager provenance.

Packages exclude local development junk, runtime state, logs, temp files, and local databases.
