# File Classification

Use this table for every meaningful file or directory in the source app.

| Category | Meaning |
| --- | --- |
| `port-as-reference` | Keep behavior/design intent, but rewrite for v3 contracts. |
| `port-nearly-as-is` | File can move with minimal changes because it is app-owned and architecture-neutral. |
| `rewrite-for-v3` | File depends on v2 runtime, APIs, paths, auth, storage, or app host assumptions. |
| `do-not-port` | File is obsolete, generated, legacy, duplicated, or incompatible with v3. |
| `defer` | File depends on a missing v3 capability that is not required for the current milestone. |
| `move-to-another-app` | File belongs to a separate app/domain rather than the target app. |
| `core-gap` | The app needs a generic v3 core capability before this can be implemented correctly. |
| `test-or-fixture` | File should become app/core test coverage or fixture material. |
| `build-artifact` | File is generated output and should only be committed when the app distribution mode requires it. |

For each item, record the reason. Do not use unexplained categories.
