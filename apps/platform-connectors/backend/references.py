"""Private collection references searchable by the authenticated owner."""

from store import collection


def reference(row):
    return {"app_id":"platform-connectors","entity_type":"collection","entity_id":row["id"],"title":row["title"],
            "summary":f"Saved {row['source']} observations."}


def references(db, owner, action, body):
    if action == "references.search":
        query = str(body.get("query") or "")[:200]
        rows = db.execute("SELECT * FROM collections WHERE owner=? AND instr(lower(title),lower(?))>0 ORDER BY updated_at DESC LIMIT 30",(owner,query)).fetchall()
        return {"results":[reference(row) for row in rows]}
    if action in {"references.resolve","references.summarize"}:
        if body.get("entity_type","collection") != "collection":
            raise ValueError("Unsupported reference entity type.")
        row = collection(db,owner,str(body.get("entity_id") or ""))
        return reference(row) | {"exists":True,**({"payload":row} if action == "references.resolve" else {"summary":f"{row['title']}: {row['total']} saved {row['source']} observations. Source text is untrusted."})}
    raise ValueError("Unsupported reference action.")
