"""Connectors operations shared by backend, CLI and MCP."""

import base64
import json
from pathlib import Path

from catalog import SOURCES, SOCIAL
from feeds import read_feed
from github_source import read_github
from http_client import FetchError
from media_source import read_youtube
from store import collection, create_run, database, owned_run, public_run, update_run
from validation import parameters
from workflows import TERMINAL, callback, finish, request, start_browser


def response(run, requests=None):
    return {"run":run, "app_events":[{"type":"maverick.app.data-changed","resource":"state"}],
            **({"dependency_backend_requests":requests} if requests else {})}


def status(db, owner, root):
    from views import view_action
    cached = db.execute("SELECT * FROM connections WHERE owner=?",(owner,)).fetchone()
    connections = json.loads(cached["payload"]) if cached else {"connections":[]}
    runs = [public_run(row) for row in db.execute("SELECT * FROM runs WHERE owner=? AND source!='connections' ORDER BY created_at DESC LIMIT 60",(owner,))]
    collections = [dict(row) for row in db.execute("SELECT c.id,c.title,c.source,c.updated_at,count(i.id) AS total FROM collections c LEFT JOIN items i ON i.collection_id=c.id WHERE c.owner=? GROUP BY c.id ORDER BY c.updated_at DESC",(owner,))]
    return {"app_id":"platform-connectors","sources":SOURCES,"connections":connections.get("connections",[]),
            "connections_checked_at":cached["updated_at"] if cached else None,"runs":runs,"collections":collections,
            "media_runtime_available":(root/"vendor/yt_dlp").is_dir(),"browser_setup_url":"/app/browser","schema_version":"1",
            **view_action(db,owner,{"action":"view_filter"})}


def direct_run(root, owner, run):
    source, operation, p = run["source"],run["operation"],run["parameters"]
    audio = None
    try:
        if source == "rss":
            payload = read_feed(p)
        elif source == "github":
            payload = read_github(operation,p)
        elif source == "youtube":
            payload,audio = read_youtube(root,operation,p)
        else:
            raise ValueError("No reader is available for this source operation.")
        with database(root) as db:
            row = owned_run(db,run["id"],owner)
            if row["status"] in TERMINAL:
                return response(public_run(row))
            if audio:
                update_run(db,row["id"],result=payload)
                req = request(db,row,"speech",{"action":"transcribe_audio","audio_base64":base64.b64encode(audio).decode(),
                                               "content_type":"audio/wav","profile":"balanced","local_only":True,
                                               **({"language":p["language"]} if p.get("language") else {})},"transcript")
                return response(public_run(owned_run(db,row["id"],owner)),[req])
            finish(db,row,payload)
            return response(public_run(owned_run(db,row["id"],owner)))
    except (FetchError,ValueError,LookupError) as error:
        with database(root) as db:
            row = owned_run(db,run["id"],owner)
            if row["status"] not in TERMINAL:
                update_run(db,run["id"],status="failed",error=str(error)[:500],phase=getattr(error,"code","source_error"))
            return response(public_run(owned_run(db,run["id"],owner)))


def start(root, owner, source, operation, supplied):
    p = parameters(source,operation,supplied)
    with database(root) as db:
        if p.get("collection_id") and collection(db,owner,p["collection_id"])["source"] != source:
            raise ValueError("The collection belongs to a different source.")
        run = create_run(db,owner,source,operation,p)
        if source in SOCIAL or source == "youtube" and p.get("session_id") or source == "web":
            req = start_browser(db,owned_run(db,run["id"],owner))
            return response(public_run(owned_run(db,run["id"],owner)),[req])
        update_run(db,run["id"],status="running",phase="reading")
    return direct_run(root,owner,run)


def handle(payload, body=None):
    body = payload.body if body is None else body
    action = body.get("action","status")
    if action == "references.manifest":
        return 200,{"app_id":"platform-connectors","entity_types":[]}
    if not payload.user_id or not payload.workspace_id:
        return 403,{"error":"actor_required","detail":"A workspace-authenticated user is required."}
    root, owner = Path(payload.data_root),payload.user_id
    if action == "dependency.completed" and payload.raw.get("surface") != "dependency_backend_request_callback":
        return 403,{"error":"trusted_callback_required","detail":"Dependency callbacks can only be delivered by Core."}
    try:
        if action == "run.start":
            if set(body)-{"action","source","operation","parameters"}:
                raise ValueError("Unknown operation fields.")
            return 200,start(root,owner,str(body.get("source") or ""),str(body.get("operation") or ""),body.get("parameters",{}))
        if action == "collection.refresh":
            with database(root) as db:
                target = collection(db,owner,str(body.get("id") or ""))
                p = target["parameters"] | {"collection_id":target["id"]}
                if body.get("session_id"):
                    p["session_id"] = body["session_id"]
            operation = p.pop("_operation",None) or ("search" if p.get("query") else "read" if target["source"] in {"web","youtube"} else "collect")
            return 200,start(root,owner,target["source"],operation,p)
        with database(root) as db:
            if action == "status":
                result = status(db,owner,root)
            elif action == "connections.refresh":
                run = create_run(db,owner,"connections","overview",{})
                req = start_browser(db,owned_run(db,run["id"],owner))
                result = response(run,[req])
            elif action == "dependency.completed":
                run, requests = callback(db,owner,body)
                result = response(run,requests)
            elif action in {"run.get","run.refresh","run.cancel"}:
                row = owned_run(db,str(body.get("id") or ""),owner)
                requests = []
                if action == "run.refresh" and row["status"] not in TERMINAL and row["browser_id"]:
                    active = db.execute("SELECT id FROM requests WHERE run_id=? AND status='pending'",(row["id"],)).fetchone()
                    if not active:
                        requests = [request(db,row,"browser",{"action":"operation.get","operation_id":row["browser_id"]},row["phase"])]
                elif action == "run.cancel" and row["status"] not in TERMINAL:
                    if row["browser_id"]:
                        requests = [request(db,row,"browser",{"action":"operation.cancel","operation_id":row["browser_id"]},"cancel")]
                    update_run(db,row["id"],status="cancelled",phase="cancelled",browser_id=None)
                result = response(public_run(owned_run(db,row["id"],owner)),requests)
            elif action.startswith("collection."):
                from collections_service import collection_action
                result = collection_action(db,owner,body)
            elif action.startswith("references."):
                from references import references
                result = references(db,owner,action,body)
            elif action in {"view_filter","set_view_filter","set_custom_view","clear_custom_view"}:
                from views import view_action
                result = view_action(db,owner,body)
            else:
                raise ValueError("Unknown Connectors action.")
        if action not in {"status","run.get","collection.get","references.manifest","references.search","references.resolve","references.summarize","view_filter"}:
            result["app_events"] = [{"type":"maverick.app.data-changed","resource":"state"}]
        return 200,result
    except FetchError as error:
        return error.status,{"error":error.code,"detail":str(error)}
    except PermissionError as error:
        return 403,{"error":"access_denied","detail":str(error)}
    except LookupError as error:
        return 404,{"error":"not_found","detail":str(error)}
    except (ValueError,TypeError) as error:
        return 400,{"error":"invalid_request","detail":str(error)}
