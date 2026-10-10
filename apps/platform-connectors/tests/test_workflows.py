"""Ownership, durable callback sequencing and the complete Instagram workflow."""

import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from catalog import SOURCES, SOCIAL
from service import handle
from store import database


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)

    def call(self, action, *, user="alice", surface="backend", **fields):
        payload=SimpleNamespace(user_id=user,workspace_id="default",data_root=str(self.root),
                                body={"action":action,**fields},raw={"surface":surface})
        return handle(payload)

    def start(self, operation="collect", **parameters):
        status,result=self.call("run.start",source="instagram",operation=operation,
                                parameters={"session_id":"chrome-"+"a"*36,"username":"marta",**parameters})
        self.assertEqual(status,200,result)
        return result

    def complete(self, request, response, **overrides):
        return self.call("dependency.completed",surface="dependency_backend_request_callback",
                         request_id=request["request_id"],dependency_alias=request["dependency_alias"],request=request,
                         dependency_backend_status="completed",dependency_backend_result={"status_code":200,"json":response},**overrides)

    def test_instagram_collect_opens_items_and_saves_refreshable_collection(self):
        started=self.start(max_items=2)
        run_id=started["run"]["id"]
        req=started["dependency_backend_requests"][0]
        self.assertEqual(req["body"]["urls"],["https://www.instagram.com/marta/","https://www.instagram.com/marta/reels/"])
        self.complete(req,{"operation_id":"collect-one","status":"queued"})
        _, refreshed=self.call("run.refresh",id=run_id)
        poll=refreshed["dependency_backend_requests"][0]
        self.assertEqual(poll["body"],{"action":"operation.get","operation_id":"collect-one"})
        _, collected=self.complete(poll,{"operation_id":"collect-one","status":"completed","result":{
            "items":[{"url":"https://www.instagram.com/p/one/","text":"snippet"},{"url":"https://www.instagram.com/reel/two/"}],"coverage":"Bounded links."}})
        for index in range(2):
            navigate=collected["dependency_backend_requests"][0]
            self.assertEqual(navigate["body"]["action"],"navigate")
            _, reading=self.complete(navigate,{"operation_id":"nav","status":"completed","result":{"url":navigate["body"]["url"]}})
            read=reading["dependency_backend_requests"][0]
            self.assertEqual(read["body"]["action"],"content.read")
            _, collected=self.complete(read,{"operation_id":"read","status":"completed","result":{
                "url":navigate["body"]["url"],"title":"Actual post","text":"Full observed content "+str(index),"observed_at":"2026-10-10"}})
        self.assertEqual(collected["run"]["status"],"completed")
        self.assertTrue(all(item["content_observed"] for item in collected["run"]["result"]["items"]))
        _, saved=self.call("collection.save",run_id=run_id,title="Instagram collection")
        self.assertEqual(saved["collection"]["total"],2)
        self.assertEqual(self.call("collection.get",id=saved["collection"]["id"],user="bob")[0],404)
        _, exported=self.call("collection.export",id=saved["collection"]["id"],format="markdown")
        export=exported["dependency_backend_requests"][0]
        self.assertEqual(export["dependency_alias"],"storage")
        _, done=self.complete(export,{"file":{"file_id":"verified-file","workspace_relative_path":export["body"]["workspace_relative_path"]}})
        self.assertEqual(done["run"]["result"]["file"]["file_id"],"verified-file")

    def test_callbacks_are_owner_scoped_trusted_idempotent_and_not_spoofable(self):
        started=self.start(read_details=False)
        req=started["dependency_backend_requests"][0]
        self.assertEqual(self.call("dependency.completed",request_id=req["request_id"])[0],403)
        self.assertEqual(self.complete(req,{},user="bob")[0],404)
        forged={**req,"body":{**req["body"],"urls":["https://www.instagram.com/another/"]}}
        self.assertEqual(self.complete(forged,{})[0],403)
        observed={"operation_id":"one","status":"completed","result":{"items":[{"url":"https://www.instagram.com/p/a/"}]}}
        _, done=self.complete(req,observed)
        self.assertFalse(done["run"]["result"]["items"][0]["content_observed"])
        _, duplicate=self.complete(req,{"operation_id":"replacement","status":"queued"})
        self.assertEqual(duplicate["run"]["status"],"completed")
        self.assertNotIn("dependency_backend_requests",duplicate)

    def test_cancelled_run_cannot_be_resumed_by_late_callback(self):
        started=self.start()
        req=started["dependency_backend_requests"][0]
        self.complete(req,{"operation_id":"one","status":"queued"})
        _, cancelled=self.call("run.cancel",id=started["run"]["id"])
        self.assertEqual(cancelled["run"]["status"],"cancelled")
        self.assertEqual(cancelled["dependency_backend_requests"][0]["body"]["action"],"operation.cancel")
        _, late=self.complete(req,{"operation_id":"one","status":"completed","result":{"items":[]}})
        self.assertEqual(late["run"]["status"],"cancelled")

    def test_cancel_before_queue_acknowledgement_cancels_the_late_browser_operation(self):
        started=self.start()
        self.call("run.cancel",id=started["run"]["id"])
        _, late=self.complete(started["dependency_backend_requests"][0],{"operation_id":"late-queued","status":"queued"})
        self.assertEqual(late["run"]["status"],"cancelled")
        cancellation=late["dependency_backend_requests"][0]
        self.assertEqual(cancellation["body"],{"action":"operation.cancel","operation_id":"late-queued"})
        _, fenced=self.complete(cancellation,{"operation_id":"late-queued","status":"cancelled"})
        self.assertEqual(fenced["run"]["status"],"cancelled")

    def test_poll_remains_waiting_until_browser_media_processing_finishes(self):
        started=self.start(operation="video",url="https://www.instagram.com/reel/a/")
        _, reading=self.complete(started["dependency_backend_requests"][0],{"status":"completed","operation_id":"nav","result":{}})
        req=reading["dependency_backend_requests"][0]
        self.assertEqual(req["body"]["action"],"video.analyze")
        self.complete(req,{"status":"processing_media","operation_id":"video"})
        _, poll=self.call("run.refresh",id=started["run"]["id"])
        _, done=self.complete(poll["dependency_backend_requests"][0],{"operation_id":"video","status":"completed","result":{
            "source_url":"https://www.instagram.com/reel/a/","frames":[{"base64":"raw-never-saved","storage":{"file_id":"frame"}}],"transcription":{"text":"Observed speech","engine":"faster-whisper"}}})
        self.assertEqual(done["run"]["status"],"completed")
        self.assertNotIn("raw-never-saved",json.dumps(done))

    def test_all_social_sources_have_real_search_routes(self):
        for source in SOCIAL:
            with self.subTest(source=source):
                status,data=self.call("run.start",source=source,operation="search",parameters={"query":"Maverick","session_id":"chrome-"+hashlib.sha256(source.encode()).hexdigest()[:36]})
                self.assertEqual(status,200,data)
                req=data["dependency_backend_requests"][0]
                self.assertEqual(req["body"]["action"],"content.collect")
                self.assertIn("Maverick",req["body"]["urls"][0])
        self.assertEqual({s["id"] for s in SOURCES},{"instagram","twitter","reddit","facebook","linkedin","youtube","rss","web","github"})
        for removed in ("exa_search","bilibili","xiaohongshu","v2ex","xueqiu","boss","xiaoyuzhou"):
            status,_=self.call("run.start",source=removed,operation="read",parameters={})
            self.assertEqual(status,400)

    def test_request_ledger_contains_hashes_instead_of_raw_media_or_exports(self):
        run=self.start()
        with database(self.root) as db:
            ledger=db.execute("SELECT body FROM requests").fetchone()[0]
        self.assertEqual(len(ledger),64)
        self.assertNotIn("instagram",ledger)

    def test_public_failure_is_terminal_and_actor_is_required(self):
        self.assertEqual(self.call("status",user=None)[0],403)
        from http_client import FetchError
        with patch("service.read_feed",side_effect=FetchError("rate_limited","Rate limited.",429)):
            _, failed=self.call("run.start",source="rss",operation="read",parameters={"url":"https://example.com/feed"})
        self.assertEqual(failed["run"]["status"],"failed")
        self.assertEqual(failed["run"]["phase"],"rate_limited")

    def test_shared_tab_cannot_interleave_operations_and_cancel_releases_it(self):
        first=self.start()
        code,error=self.call("run.start",source="instagram",operation="read",parameters=first["run"]["parameters"])
        self.assertEqual(code,400)
        self.assertIn("already observing",error["detail"])
        self.call("run.cancel",id=first["run"]["id"])
        self.assertEqual(self.start()["run"]["status"],"waiting")

    def test_profile_collection_refresh_preserves_action_and_partial_observations(self):
        started=self.start(operation="profile")
        _, reading=self.complete(started["dependency_backend_requests"][0],{"operation_id":"nav","status":"completed","result":{}})
        _, done=self.complete(reading["dependency_backend_requests"][0],{"operation_id":"read","status":"completed","result":{"url":"https://www.instagram.com/marta/","text":"Profile bio"}})
        _, saved=self.call("collection.save",run_id=done["run"]["id"],title="Profile")
        _, refreshed=self.call("collection.refresh",id=saved["collection"]["id"])
        self.assertEqual(refreshed["run"]["operation"],"profile")
        self.call("run.cancel",id=refreshed["run"]["id"])
        partial=self.start()
        _, detail=self.complete(partial["dependency_backend_requests"][0],{"operation_id":"collect","status":"completed","result":{"items":[{"url":"https://www.instagram.com/p/a/"}],"observations":[{"url":"https://www.instagram.com/marta/","text":"Bio"}]}})
        self.complete(detail["dependency_backend_requests"][0],{"operation_id":"failed","status":"failed","result":{"detail":"Tab unavailable"}})
        _, retained=self.call("collection.save",run_id=partial["run"]["id"],title="Partial")
        self.assertEqual(retained["collection"]["total"],2)
        self.assertTrue(any(item["text"]=="Bio" for item in retained["collection"]["items"] if item.get("text")))

    def test_expired_work_releases_tab_without_expiring_saved_collections(self):
        started=self.start()
        with database(self.root) as db:
            db.execute("UPDATE runs SET updated_at='2020-01-01' WHERE id=?",(started["run"]["id"],))
        self.start()
        _, expired=self.call("run.get",id=started["run"]["id"])
        self.assertEqual(expired["run"]["status"],"failed")
        self.assertEqual(expired["run"]["phase"],"expired")

    def test_reference_manifest_is_public_metadata_without_opening_private_data(self):
        code,manifest=self.call("references.manifest",user=None)
        self.assertEqual(code,200)
        self.assertEqual(manifest["app_id"],"platform-connectors")
        self.assertFalse((self.root/"connectors.sqlite3").exists())

    def test_views_and_references_never_cross_owners(self):
        started=self.start(read_details=False)
        self.complete(started["dependency_backend_requests"][0],{"operation_id":"one","status":"completed","result":{"items":[{"url":"https://www.instagram.com/p/a/"}]}})
        _, saved=self.call("collection.save",run_id=started["run"]["id"],title="Private collection")
        identifier=saved["collection"]["id"]
        _, refs=self.call("references.search",query="Private")
        self.assertEqual(refs["results"][0]["entity_id"],identifier)
        self.assertEqual(self.call("references.search",query="Private",user="bob")[1]["results"],[])
        self.assertEqual(self.call("set_custom_view",refs=[refs["results"][0]],user="bob")[0],404)
        self.assertEqual(self.call("set_custom_view",refs=[refs["results"][0]])[0],200)
        self.assertEqual(self.call("view_filter")[1]["view_state"]["ids"],[identifier])
        _, refined=self.call("set_view_filter",query="Private")
        self.assertEqual(refined["view_state"]["mode"],"custom")
        self.assertEqual(refined["view_state"]["ids"],[identifier])


if __name__ == "__main__":
    unittest.main()
