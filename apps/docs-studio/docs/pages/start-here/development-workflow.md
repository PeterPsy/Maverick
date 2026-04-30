# Development workflow

## Before changing code

- Read the relevant architecture source of truth.
- Inspect the real code and current git state.
- Keep the change inside the smallest app or core domain that owns the behavior.
- Ask only when product behavior, data model, or destructive action is ambiguous.

## While implementing

- Prefer small domain-oriented files.
- Remove obsolete scaffolding when replacing a direction.
- Keep documentation and implementation aligned in the same change.
- Avoid compatibility shims unless a written decision requires them.

## Final review pass

- Run the smallest relevant verification.
- Review the diff for dead code, stale names, and documentation drift.
- Remove caches, temporary files, and experimental leftovers.
- Summarize registration, installation, and enabled state when creating apps.

> **Quality bar:** do not claim completion when only a scaffold exists.


## Change shape

Prefer changes that are easy to review in one sitting. A good Maverick change usually has:

- one clear owner
- one contract or UI behavior being improved
- focused tests that prove the behavior
- documentation updates when architecture or workflow changed

## Common pitfalls

| Pitfall | Better approach |
| --- | --- |
| Adding app-specific behavior in core | Add or use a generic platform surface |
| Leaving scaffold behavior in a new app | Replace it with real product behavior before calling it done |
| Updating source without rebuilding frontend assets | Run the app frontend build |
| Writing app data outside `data/<app_id>` | Keep the app data boundary intact |

## Review language

When reviewing, lead with bugs, regressions, missing tests, and architectural drift. Summaries come after findings, not before.
