"""Persisted collection filters and curated owner-checked references for agents."""

import json

from catalog import BY_ID
from store import collection, encoded
from validation import text


def view_action(db, owner, body):
    action = body["action"]
    if action == "view_filter":
        row = db.execute("SELECT payload FROM views WHERE owner=?",(owner,)).fetchone()
        return {"view_state":json.loads(row[0]) if row else {"mode":"default","query":"","source":"","ids":[]}}
    state = {"mode":"default","query":"","source":"","ids":[]}
    if action == "set_view_filter":
        state = view_action(db,owner,{"action":"view_filter"})["view_state"]
        state["query"] = text(body.get("query",state.get("query","")),"query",200)
        state["source"] = text(body.get("source",state.get("source","")),"source",40)
        if state["source"] and state["source"] not in BY_ID:
            raise ValueError("Unknown source filter.")
    elif action == "set_custom_view":
        refs = body.get("refs")
        if not isinstance(refs,list) or any(not isinstance(ref,dict) or ref.get("app_id") != "platform-connectors" or ref.get("entity_type") != "collection" for ref in refs):
            raise ValueError("Provide owned Connectors collection references.")
        ids = [ref.get("entity_id") for ref in refs]
        if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(identity,str) for identity in ids):
            raise ValueError("Provide at most 100 collection ids.")
        for identity in ids:
            collection(db,owner,identity,limit=1)
        state.update(mode="custom",ids=list(dict.fromkeys(ids)),title=text(body.get("title",""),"title",160))
    elif action != "clear_custom_view":
        raise ValueError("Unknown collection view action.")
    db.execute("INSERT INTO views VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload",(owner,encoded(state)))
    return {"view_state":state}
