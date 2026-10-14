"""Source fixtures exercise API parsing, transcripts and public network policy."""

import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from feeds import parse_feed
from github_source import read_github
from http_client import FetchError, Response, fetch, public_addresses, public_target
from media_source import captions
from validation import parameters


def response(data):
    return Response("https://example.com/",200,{},json.dumps(data).encode())


class SourceTests(unittest.TestCase):
    def test_rss_atom_deduplication_dates_audio_and_entity_rejection(self):
        rss=b'<rss><channel><item><title>Post</title><link>https://example.com/one</link><description>&lt;p&gt;Hello&lt;/p&gt;</description><pubDate>Today</pubDate><enclosure url="https://example.com/audio.mp3" type="audio/mpeg"/></item><item><link>https://example.com/one</link></item></channel></rss>'
        result=parse_feed(rss,"https://example.com/feed",30)
        self.assertEqual(len(result["items"]),1)
        self.assertEqual(result["items"][0]["text"],"Hello")
        self.assertEqual(result["items"][0]["enclosures"][0]["content_type"],"audio/mpeg")
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id><title>Atom</title><link href="/article"/><summary>Actual summary</summary></entry></feed>'
        self.assertEqual(parse_feed(atom,"https://example.com/feed",1)["items"][0]["url"],"https://example.com/article")
        for unsafe in [b'<!DOCTYPE rss [<!ENTITY x "x">]><rss/>','<!DOCTYPE rss [<!ENTITY x "x">]><rss/>'.encode('utf-16'),b'<html><body>Not a feed</body></html>']:
            with self.assertRaises(FetchError):parse_feed(unsafe,"https://example.com/",10)

    def test_github_repository_issue_collection_and_search(self):
        p={"url":"https://github.com/org/repo/issues/10","max_items":2}
        with patch("github_source.fetch",side_effect=[response({"html_url":p["url"],"title":"Issue","body":"Observed issue","comments":1}),response([{"html_url":p["url"]+"#comment","body":"Observed reply","user":{"login":"alice"}}])]) as mocked:
            result=read_github("read",p)
        self.assertEqual(result["items"][1]["text"],"Observed reply")
        self.assertTrue(all(call.kwargs["allowed_hosts"]=={"api.github.com"} for call in mocked.call_args_list))
        with patch("github_source.fetch",return_value=response({"items":[{"html_url":"https://github.com/org/repo","full_name":"org/repo","description":"Summary"}],"total_count":100})):
            result=read_github("search",{"query":"loopino","max_items":3})
        self.assertTrue(result["truncated"])
        self.assertFalse(result["items"][0]["content_observed"])

    def test_github_missing_readme_keeps_metadata_without_claiming_content(self):
        repository={"html_url":"https://github.com/org/repo","full_name":"org/repo","description":"Metadata summary"}
        with patch("github_source.fetch",side_effect=[response(repository),FetchError("not_found","README unavailable.",404)]):
            observed=read_github("read",{"url":repository["html_url"],"max_items":10})
        self.assertFalse(observed["items"][0]["content_observed"])
        self.assertEqual(observed["source_error"]["code"],"not_found")
        self.assertIn("metadata only",observed["coverage"])

    def test_youtube_captions_keep_measured_times_and_language(self):
        data={"automatic_captions":{"en":[{"ext":"json3","url":"https://www.youtube.com/api/timedtext?v=one"}]}}
        with patch("media_source.fetch",return_value=response({"events":[{"tStartMs":1200,"dDurationMs":2300,"segs":[{"utf8":"Hello"},{"utf8":" world"}]}]})):
            segments,language,automatic=captions(data,"en")
        self.assertEqual(segments,[{"start":1.2,"end":3.5,"text":"Hello world"}])
        self.assertEqual(language,"en")
        self.assertTrue(automatic)

    def test_public_target_and_dns_reject_credentials_local_and_mixed_answers(self):
        for url in ['file:///etc/passwd','https://secret@example.com/','http://localhost/','https://example.com:8080/','https://example.com\\@127.0.0.1/']:
            with self.assertRaises(FetchError):public_target(url)
        for addresses in [['127.0.0.1'],['8.8.8.8','10.1.2.3'],['::1'],['169.254.169.254']]:
            with patch("http_client.socket.getaddrinfo",return_value=[(socket.AF_INET,socket.SOCK_STREAM,0,'',(ip,443)) for ip in addresses]):
                with self.assertRaises(FetchError):public_addresses('example.com',443)

    def test_redirect_revalidates_dns_and_strips_cross_host_credentials(self):
        class Connection:
            def __init__(self,*args):pass
            def request(self,*args,**kwargs):calls.append(kwargs["headers"])
            def getresponse(self):return responses.pop(0)
            def close(self):pass
        class Redirect:
            status=302
            def getheaders(self):return [('location','https://other.example.com/')]
        class Success:
            status=200
            def getheaders(self):return []
            def read(self,n):return b'{}'
        calls,responses=[],[Redirect(),Success()]
        with patch('http_client.public_addresses',return_value=['8.8.8.8']) as dns,patch('http_client.PinnedHTTPSConnection',Connection):
            fetch('https://example.com/',headers={'Authorization':'private-key','Cookie':'private-cookie'})
        self.assertEqual(dns.call_count,2)
        self.assertNotIn('Authorization',calls[1])
        self.assertNotIn('Cookie',calls[1])

    def test_inputs_reject_spoofed_actor_and_unbounded_budgets(self):
        for supplied in [{'user_id':'bob'},{'max_seconds':181},{'max_items':True},{'url':'https://www.youtube.com/redirect?url=http://127.0.0.1'},{'url':'https://www.youtube.com/watch?v=not-a-valid-id'}]:
            with self.assertRaises((ValueError,FetchError)):parameters('youtube','read',supplied)


if __name__ == '__main__':
    unittest.main()
