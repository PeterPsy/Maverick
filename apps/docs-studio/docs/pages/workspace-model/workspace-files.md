# Files and storage

## Generated files

When an agent writes a file under:

```text
storage/generated/
```

the file exists immediately as a generated workspace artifact and should be discoverable by Storage.

## Uploaded files

Uploads land under:

```text
storage/uploaded/<file_id>/<safe_filename>
```

## Stable identity

Storage and app references should prefer stable `file_id` values. Paths remain useful for navigation and debugging, but identity should survive ordinary rename or re-indexing.

The Storage app keeps its derived file inventory in:

```text
data/storage/files.json
```

Storage-managed writes and moves update this index synchronously. Catalog reconciliation can scan `storage/uploaded/` and `storage/generated/` to assign ids to files created out of band.


## File lifecycle

1. A file is uploaded or generated under `storage/`.
2. Storage indexes metadata from the filesystem.
3. Apps reference the file through stable identity.
4. Preview, rename, and delete operations validate the path against workspace storage roots.

## Safety rules

- Do not store generic uploads inside one app's private data directory.
- Do not treat `tmp/` or `runtime/` as durable output locations.
- Do not silently overwrite stable file identities.
