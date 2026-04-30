# Third-Party Inventory

For the first public Maverick release, the direct dependency inventory is generated into:

- `docs/legal/third_party_inventory.json`

Regenerate it with:

```bash
python3 scripts/generate_dependency_inventory.py
```

This inventory is meant to make dependency review easier during the first public open source phase.

It is not yet a full transitive SBOM or signed provenance artifact.
