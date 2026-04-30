# SDK overview

The Maverick App SDK creates valid app source trees and moves workspace-local apps through the official lifecycle. It does not bypass the core.

## Canonical flow

```bash
maverick sdk templates
maverick sdk docs
maverick core cli run core.app-sdk.create --app-id my-app --template-id data-app --json
maverick core cli run core.app-sdk.validate --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.register-local --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.install-local --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.status --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.package --app-id my-app --workspace default --json
```

## What the SDK enforces

- contract parsing through the canonical parser
- declared surface completeness
- workspace-local registration and installation
- app data root creation
- deterministic packaging

## Developer Kit

The `developer-kit` app exposes the SDK workflow through a browser UI. Permission checks remain in the authenticated SDK API and app-hosting policy layer.

> **Source:** `docs/app-sdk/getting_started.md`, `docs/architecture/app_sdk_architecture.md`
