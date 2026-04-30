# Provider credentials and secrets

Provider credentials are platform-controlled secrets, not app-owned workspace data.

## Separate records

| Record | Contains |
| --- | --- |
| provider definition | id, kind, adapter, display metadata |
| capability metadata | models, modes, tool support, streaming support |
| credential binding | secret reference or alias |
| workspace selection | active provider choice for one workspace |

## Secret rules

- Raw API keys do not go in `data/<app_id>`.
- Runtime records should store secret references, not values.
- Resolved values are short-lived runtime input.
- Export/import should include placeholders or references, never raw secrets.

## Example

An OpenAI-compatible provider can have an API base URL, model list, and secret binding. The runtime adapter resolves the key only when constructing a controlled provider request.
