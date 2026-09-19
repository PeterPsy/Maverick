"""Integration receipts round-trip as history, never restored execution authority."""

import json
from errors import ValidationError
from store import row_to_dict


def export_integrations(db):
    return [row_to_dict(row) for row in db.execute('SELECT * FROM integration_operations ORDER BY id')]


def restore_integrations(db, rows):
    if not isinstance(rows, list):
        raise ValidationError('Integration receipts must be an array.')
    columns = [row['name'] for row in db.execute('PRAGMA table_info(integration_operations)')]
    for record in rows:
        if not isinstance(record, dict) or not record.get('id'):
            raise ValidationError('Integration receipts need a stable ID.')
        # Import is not an operation editor, nor a way to reset a delivery claim.
        existing = db.execute('SELECT 1 FROM integration_operations WHERE id=?', (record['id'],)).fetchone()
        if existing:
            continue
        values = {}
        for key in columns:
            value = record.get(key[:-5] if key.endswith('_json') else key)
            values[key] = json.dumps(value or {}) if key.endswith('_json') else value
        values.update(status='succeeded' if record.get('status') == 'succeeded' else 'restored', attempt_id='')
        db.execute(f"INSERT INTO integration_operations({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", list(values.values()))
        if record.get('proposal_id'):
            db.execute("UPDATE workflow_proposals SET status=?, approved_at='' WHERE id=?", ('applied' if values['status'] == 'succeeded' else 'dismissed', record['proposal_id']))
