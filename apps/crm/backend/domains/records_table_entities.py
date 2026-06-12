"""Per-entity SQL projection config for the CRM records table."""

from __future__ import annotations


def records_table_entity_config(entity_type: str) -> dict[str, str]:
    if entity_type == "lead":
        return {
            "table": "leads",
            "alias": "l",
            "joins": """
              LEFT JOIN accounts lead_account_ref ON lead_account_ref.id = l.account_id AND lead_account_ref.deleted_at IS NULL
              LEFT JOIN contacts lead_contact_ref ON lead_contact_ref.id = l.contact_id AND lead_contact_ref.deleted_at IS NULL
            """,
            "title": "l.display_name",
            "search": "l.display_name || ' ' || l.email || ' ' || l.company || ' ' || l.domain || ' ' || l.summary",
            "owner": "l.owner_id",
            "status": "l.status",
            "stage": "''",
            "value": "0",
            "probability": "0",
            "close_date": "''",
            "last_activity_at": "''",
            "next_action": "''",
            "open_task_count": "0",
            "open_deal_value": "0",
            "contact_count": "0",
            "weighted_value": "0",
            "deal_age_days": "0",
            "account_label": "COALESCE(NULLIF(lead_account_ref.name, ''), NULLIF(l.company, ''), NULLIF(l.domain, ''), '')",
            "contact_label": "COALESCE(lead_contact_ref.display_name, '')",
        }
    if entity_type == "account":
        return {
            "table": "accounts",
            "alias": "a",
            "joins": """
              LEFT JOIN activity_rollups ar ON ar.entity_type = 'account' AND ar.entity_id = a.id
              LEFT JOIN task_counts tc ON tc.entity_type = 'account' AND tc.entity_id = a.id
              LEFT JOIN next_tasks nt ON nt.entity_type = 'account' AND nt.entity_id = a.id
              LEFT JOIN deal_rollups dr ON dr.entity_type = 'account' AND dr.entity_id = a.id
              LEFT JOIN contact_counts cc ON cc.entity_id = a.id
            """,
            "title": "a.name",
            "search": "a.name || ' ' || a.domain || ' ' || a.industry || ' ' || a.summary",
            "owner": "a.owner_id",
            "status": "a.status",
            "stage": "''",
            "value": "0",
            "probability": "0",
            "close_date": "''",
            "last_activity_at": "COALESCE(ar.last_activity_at, '')",
            "next_action": "COALESCE(nt.next_action, '')",
            "open_task_count": "COALESCE(tc.open_task_count, 0)",
            "open_deal_value": "COALESCE(dr.open_deal_value, 0)",
            "contact_count": "COALESCE(cc.contact_count, 0)",
            "weighted_value": "0",
            "deal_age_days": "0",
            "account_label": "a.name",
            "contact_label": "''",
        }
    if entity_type == "contact":
        return {
            "table": "contacts",
            "alias": "c",
            "joins": """
              LEFT JOIN accounts contact_account_ref ON contact_account_ref.id = c.account_id AND contact_account_ref.deleted_at IS NULL
              LEFT JOIN activity_rollups ar ON ar.entity_type = 'contact' AND ar.entity_id = c.id
              LEFT JOIN task_counts tc ON tc.entity_type = 'contact' AND tc.entity_id = c.id
              LEFT JOIN next_tasks nt ON nt.entity_type = 'contact' AND nt.entity_id = c.id
              LEFT JOIN deal_rollups dr ON dr.entity_type = 'contact' AND dr.entity_id = c.id
            """,
            "title": "c.display_name",
            "search": "c.display_name || ' ' || c.email || ' ' || c.role || ' ' || c.summary",
            "owner": "c.owner_id",
            "status": "''",
            "stage": "''",
            "value": "0",
            "probability": "0",
            "close_date": "''",
            "last_activity_at": "COALESCE(ar.last_activity_at, '')",
            "next_action": "COALESCE(nt.next_action, '')",
            "open_task_count": "COALESCE(tc.open_task_count, 0)",
            "open_deal_value": "COALESCE(dr.open_deal_value, 0)",
            "contact_count": "0",
            "weighted_value": "0",
            "deal_age_days": "0",
            "account_label": "COALESCE(contact_account_ref.name, '')",
            "contact_label": "c.display_name",
        }
    return {
        "table": "deals",
        "alias": "d",
        "joins": """
          LEFT JOIN accounts deal_account_ref ON deal_account_ref.id = d.account_id AND deal_account_ref.deleted_at IS NULL
          LEFT JOIN contacts deal_contact_ref ON deal_contact_ref.id = d.contact_id AND deal_contact_ref.deleted_at IS NULL
          LEFT JOIN activity_rollups ar ON ar.entity_type = 'deal' AND ar.entity_id = d.id
          LEFT JOIN task_counts tc ON tc.entity_type = 'deal' AND tc.entity_id = d.id
          LEFT JOIN next_tasks nt ON nt.entity_type = 'deal' AND nt.entity_id = d.id
        """,
        "title": "d.name",
        "search": "d.name || ' ' || d.stage || ' ' || d.summary",
        "owner": "d.owner_id",
        "status": "d.stage",
        "stage": "COALESCE(NULLIF(d.stage, ''), d.stage_id)",
        "value": "d.value",
        "probability": "d.probability",
        "close_date": "d.close_date",
        "last_activity_at": "COALESCE(ar.last_activity_at, '')",
        "next_action": "COALESCE(nt.next_action, '')",
        "open_task_count": "COALESCE(tc.open_task_count, 0)",
        "open_deal_value": "0",
        "contact_count": "0",
        "weighted_value": "round(d.value * d.probability, 2)",
        "deal_age_days": "CAST(max(0, julianday('now') - julianday(d.created_at)) AS INTEGER)",
        "account_label": "COALESCE(deal_account_ref.name, '')",
        "contact_label": "COALESCE(deal_contact_ref.display_name, '')",
    }
