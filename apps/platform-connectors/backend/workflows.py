"""Durable Browser dependency orchestration and authenticated callbacks."""

import hashlib
import json
from uuid import uuid4

from catalog import SOCIAL, observed_item, profile_url, search_url
from content import result
from store import add_items, encoded, now, owned_run, public_run, update_run


TERMINAL = {"completed","failed","cancelled"}


def fingerprint(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def request(db, run, alias, body, phase):
    identifier = str(uuid4())
    db.execute("INSERT INTO requests(id,run_id,alias,body,phase,created_at) VALUES(?,?,?,?,?,?)",
               (identifier,run["id"],alias,fingerprint(body),phase,now()))
    if run["status"] not in TERMINAL:
        update_run(db,run["id"],status="waiting",phase=phase,browser_id=None)
    return {"request_id":identifier,"dependency_alias":alias,"body":body,
            "callback":{"action":"dependency.completed","payload":{}}}


def browser_request(db, run, action, phase, **fields):
    parameters = json.loads(run["parameters"])
    return request(db,run,"browser",{"action":action,"session_id":parameters["session_id"],**fields},phase)


def start_browser(db, run):
    source, operation = run["source"],run["operation"]
    p = json.loads(run["parameters"])
    if source == "connections":
        return request(db,run,"browser",{"action":"companion.overview"},"connections")
    if source not in SOCIAL and not (source == "youtube" and p.get("session_id")):
        body = {"action":"research.search","query":p["query"]} if operation == "search" else {"action":"research.open","url":p["url"]}
        return request(db,run,"browser",body,"research")
    url = search_url(source,p["query"]) if operation == "search" else p.get("url") or (profile_url(source,p["username"]) if p.get("username") else None)
    if operation in {"collect","search"}:
        if not url:
            raise ValueError("Enter a profile or page URL to collect.")
        urls = [url]
        if source == "instagram" and p["include_reels"]:
            from urllib.parse import urlsplit
            path = urlsplit(url).path.strip("/")
            if path and "/" not in path:
                urls.append(url.rstrip("/")+"/reels/")
        return browser_request(db,run,"content.collect","collect",urls=urls,max_items=p["max_items"],max_batches=p["max_batches"])
    if url:
        return browser_request(db,run,"navigate","navigate",url=url)
    return next_read(db,run,"read")


def next_read(db, run, phase):
    p = json.loads(run["parameters"])
    if run["operation"] in {"video","transcript"} and phase == "read":
        return browser_request(db,run,"video.analyze","video",frame_count=p["frame_count"],max_seconds=p["max_seconds"],
                               include_audio=p["include_audio"],save_evidence=True)
    return browser_request(db,run,"content.read",phase,max_chars=100000,max_items=200)


def clean_media(value):
    if isinstance(value,dict):
        return {k:clean_media(v) for k,v in value.items() if k not in {"base64","audio_base64","content_base64","connector_secret"}}
    if isinstance(value,list):
        return [clean_media(v) for v in value[:10000]]
    return value


def finish(db, run, payload):
    p = json.loads(run["parameters"])
    if p.get("collection_id"):
        # Ownership was checked before dispatch; check again before writing.
        target = db.execute("SELECT id FROM collections WHERE id=? AND owner=?",(p["collection_id"],run["owner"])).fetchone()
        if target:
            add_items(db,p["collection_id"],payload.get("context_items",[]) + payload.get("items",[]))
    payload.pop("detail_queue",None)
    payload.pop("detail_index",None)
    update_run(db,run["id"],status="completed",phase="completed",result=payload,browser_id=None)


def next_detail(db, run, payload):
    index = payload.get("detail_index",0)
    queue = payload.get("detail_queue",[])
    if index >= len(queue):
        finish(db,run,payload)
        return []
    update_run(db,run["id"],result=payload)
    return [browser_request(db,run,"navigate","detail.navigate",url=queue[index])]


def accept_browser(db, run, phase, response):
    if response.get("operation_id") and response.get("status") in {"queued","running","processing_media"}:
        update_run(db,run["id"],status="waiting",phase=phase,browser_id=response["operation_id"])
        return []
    if response.get("status") in {"failed","cancelled","expired"}:
        raise ValueError("Browser operation " + response["status"] + ": " + str((response.get("result") or {}).get("detail") or (response.get("result") or {}).get("error") or "The shared tab may be unavailable."))
    observation = response.get("result") if response.get("operation_id") else response
    if not isinstance(observation,dict) or observation.get("error"):
        raise ValueError(str((observation or {}).get("detail") or (observation or {}).get("error") or "The source returned no observation."))
    source = run["source"]
    p = json.loads(run["parameters"])
    if phase == "connections":
        db.execute("INSERT INTO connections VALUES(?,?,?) ON CONFLICT(owner) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                   (run["owner"],encoded(observation),now()))
        finish(db,run,{"connections_updated":True})
    elif phase == "navigate":
        return [next_read(db,run,"read")]
    elif phase == "detail.navigate":
        return [next_read(db,run,"detail.read")]
    elif phase == "collect":
        items = observation.get("items",[])[:p["max_items"]]
        payload = clean_media(observation)
        payload["items"] = [entry | {"source":source,"content_observed":False,
                                     "provenance":{"backend":"user_shared_chrome","data_class":"personal","trust":"untrusted_source_content"}} for entry in items]
        pages = observation.get("observations") or []
        payload["context_items"] = [observed_item(source,page | {"backend":"user_shared_chrome"}) for page in pages[:2] if isinstance(page,dict)]
        payload["detail_queue"] = [entry["url"] for entry in items[:p["max_details"]] if entry.get("url")] if p["read_details"] else []
        payload["detail_index"] = 0
        return next_detail(db,run,payload)
    elif phase == "detail.read":
        payload = json.loads(run["result"])
        index = payload["detail_index"]
        url = payload["detail_queue"][index]
        observed = observed_item(source,observation,url)
        payload["items"] = [entry | observed if entry.get("url") == url else entry for entry in payload["items"]]
        payload["detail_index"] = index+1
        return next_detail(db,run,payload)
    elif phase == "video":
        media = clean_media(observation)
        finish(db,run,result([observed_item(source,observation | {"backend":"user_shared_chrome"}) | {"media":media}],
                             coverage="Sampled frames and bounded tab audio, not every frame of the video."))
    elif phase == "research":
        text = observation.get("snapshot") or observation.get("text") or observation.get("content") or ""
        if isinstance(text,dict):
            text = text.get("text") or encoded(text)
        links = observation.get("links") or []
        items = [observed_item(source,{"url":link.get("url",""),"title":link.get("text") or link.get("title"),"text":""}) | {"content_observed":False}
                 for link in links[:p["max_items"]] if isinstance(link,dict) and link.get("url")] if run["operation"] == "search" else []
        if not items:
            items = [observed_item(source,{"url":observation.get("url") or p.get("url") or "", "title":observation.get("title") or p.get("query"),"text":text})]
        finish(db,run,result(items,text=text,coverage="Browser research snapshot. Search snippets do not establish full article coverage."))
    else:
        finish(db,run,result([observed_item(source,observation)],coverage="Rendered page content at the observation time; collapsed or unloaded content is excluded."))
    return []


def callback(db, owner, body):
    pending = db.execute("SELECT * FROM requests WHERE id=?",(str(body.get("request_id") or ""),)).fetchone()
    if pending is None:
        raise LookupError("No matching dependency request.")
    run = owned_run(db,pending["run_id"],owner)
    original = body.get("request") or {}
    if body.get("dependency_alias") != pending["alias"] or original.get("request_id") != pending["id"] or original.get("dependency_alias") != pending["alias"] or fingerprint(original.get("body")) != pending["body"]:
        raise PermissionError("The callback does not match the dispatched dependency request.")
    if pending["status"] != "pending":
        return public_run(run),[]
    db.execute("UPDATE requests SET status='done' WHERE id=?",(pending["id"],))
    envelope = body.get("dependency_backend_result") or {}
    response = envelope.get("json") or {}
    if run["status"] in TERMINAL:
        # Cancellation can precede the provider's first queue acknowledgement.
        # Stop that late Browser operation without resuming the cancelled run.
        if run["status"] == "cancelled" and pending["alias"] == "browser" and response.get("operation_id") and response.get("status") in {"queued","running","processing_media"}:
            cancel = request(db,run,"browser",{"action":"operation.cancel","operation_id":response["operation_id"]},"cancel")
            return public_run(run),[cancel]
        return public_run(run),[]
    if body.get("dependency_backend_status") != "completed" or envelope.get("status_code",500)>=400 or response.get("error"):
        update_run(db,run["id"],status="failed",error=str(response.get("detail") or response.get("error") or "The dependency request failed.")[:500])
        return public_run(owned_run(db,run["id"],owner)),[]
    try:
        if pending["phase"] == "cancel":
            return public_run(run),[]
        if pending["alias"] == "speech":
            payload = json.loads(run["result"])
            transcript = clean_media(response)
            if transcript.get("engine") not in {"faster-whisper","whisper.cpp"}:
                raise ValueError("A local transcription engine is required.")
            payload["items"][0]["transcript"] = transcript | {"status":"completed","local_only":True}
            finish(db,run,payload)
            requests = []
        elif pending["alias"] == "storage":
            file = response.get("file") or {}
            identity = file.get("file_id") or file.get("stable_storage_file_id") or file.get("id")
            path = file.get("workspace_relative_path") or response.get("workspace_relative_path")
            if not identity or path != original["body"].get("workspace_relative_path"):
                raise ValueError("Storage did not verify the requested export.")
            finish(db,run,{"file":{"file_id":identity,"workspace_relative_path":path,"deep_link":f"/app/storage?file_id={identity}"},"items":[]})
            requests = []
        else:
            requests = accept_browser(db,run,pending["phase"],response)
    except (ValueError,KeyError,TypeError) as error:
        update_run(db,run["id"],status="failed",error=str(error)[:500])
        requests = []
    return public_run(owned_run(db,run["id"],owner)),requests
