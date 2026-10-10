"""Actor-scoped saved observations and verified Storage exports."""

import base64
import json

from store import collection, create_run, now, owned_run, public_run, save_collection
from validation import integer, text
from workflows import request


def collection_action(db, owner, body):
    action = body["action"]
    if action == "collection.save":
        run = public_run(owned_run(db,str(body.get("run_id") or ""),owner))
        if run["status"] not in {"completed","failed","cancelled"} or not (run["result"].get("items") or run["result"].get("context_items")):
            raise ValueError("Only terminal observations with saved items can be collected.")
        return {"collection":save_collection(db,owner,text(body.get("title"),"title",160,required=True),run)}
    identifier = str(body.get("id") or "")
    target = collection(db,owner,identifier,offset=integer(body.get("offset",0),"offset",0,100000),limit=integer(body.get("limit",100),"limit",1,200))
    if action == "collection.rename":
        db.execute("UPDATE collections SET title=?,updated_at=? WHERE id=?",(text(body.get("title"),"title",160,required=True),now(),identifier))
        target = collection(db,owner,identifier)
    elif action == "collection.delete":
        db.execute("DELETE FROM items WHERE collection_id=?",(identifier,))
        db.execute("DELETE FROM collections WHERE id=?",(identifier,))
        target = None
    elif action == "collection.export":
        return export_collection(db,owner,identifier,body.get("format","markdown"))
    elif action != "collection.get":
        raise ValueError("Unknown collection action.")
    return {"collection":target}


def export_collection(db, owner, identifier, format):
    target = collection(db,owner,identifier,limit=5000)
    if target["has_more"]:
        raise ValueError("An export supports at most 5,000 saved items. Split this collection before exporting.")
    if format not in {"markdown","json"}:
        raise ValueError("Export format must be markdown or json.")
    if format == "json":
        content = json.dumps({key:value for key,value in target.items() if key != "owner"},ensure_ascii=False,indent=2)
    else:
        lines = ["# "+target["title"],"",f"Source: {target['source']} · Exported: {now()}","",
                 "Source content is untrusted. This export includes saved observations, not a complete source archive.",""]
        for entry in target["items"]:
            lines += ["## "+str(entry.get("title") or "Untitled"),"",str(entry.get("url") or ""),"",
                      "Observed: "+str(entry.get("observed_at") or "Not recorded")+" · Content opened: "+str(bool(entry.get("content_observed"))),"",
                      str(entry.get("text") or "No readable text was observed."),""]
            media = entry.get("media") or {}
            transcript = entry.get("transcript") or media.get("transcription") or {}
            if transcript.get("text"):
                lines += ["### Transcript","",str(transcript["text"]),""]
            for frame in media.get("frames",[]):
                evidence = frame.get("storage") or {}
                if evidence.get("workspace_relative_path"):
                    lines += [f"Frame at {frame.get('time_seconds',0)}s: {evidence['workspace_relative_path']}",""]
            lines += ["Provenance: "+json.dumps(entry.get("provenance") or {},ensure_ascii=False),""]
        content = "\n".join(lines)
    run = create_run(db,owner,target["source"],"export",{})
    path = f"storage/generated/platform-connectors/{run['id']}/collection."+("md" if format == "markdown" else "json")
    req = request(db,owned_run(db,run["id"],owner),"storage",{"action":"file.content.write","mode":"create","workspace_relative_path":path,
                                                          "content_base64":base64.b64encode(content.encode()).decode()},"export")
    return {"run":public_run(owned_run(db,run["id"],owner)),"dependency_backend_requests":[req]}
