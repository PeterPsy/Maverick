"""RSS and Atom parsing without DTD/entity processing."""

import re
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from content import item, result, safe_url
from http_client import FetchError, fetch


def parse_feed(content: bytes, url: str, limit: int) -> dict:
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)", content.replace(b"\0",b""), re.I):
        raise FetchError("unsafe_feed", "Feeds containing DTDs or entities are not supported.", 400)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise FetchError("invalid_feed", "The source is not a valid RSS or Atom feed.") from error
    if root.tag.split("}")[-1] not in {"rss", "feed", "RDF"}:
        raise FetchError("invalid_feed", "The source is not an RSS or Atom feed.")

    def children(node, name):
        return [child for child in node if child.tag.split("}")[-1] == name]

    def value(node, *names):
        for name in names:
            matches = children(node,name)
            if matches:
                return "".join(matches[0].itertext()).strip()
        return ""

    entries = [node for node in root.iter() if node.tag.split("}")[-1] in {"item","entry"}]
    items, seen = [], set()
    for entry in entries:
        links = children(entry,"link")
        link = next((node.get("href") for node in links if node.get("href") and node.get("rel","alternate") == "alternate"), None) or value(entry,"link")
        canonical = safe_url(urljoin(url, link or ""))
        identity = canonical if link else value(entry,"guid","id")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        enclosures = [{"url":safe_url(urljoin(url,node.get("url") or node.get("href") or "")),"content_type":node.get("type")}
                      for node in entry if node.tag.split("}")[-1] == "enclosure" or node.tag.split("}")[-1] == "link" and node.get("rel") == "enclosure"]
        if not link:
            canonical = url + "#entry-" + str(len(items)+1)
        items.append(item("rss", canonical, value(entry,"title"), value(entry,"encoded","content","description","summary"),
                          published_at=value(entry,"pubDate","published","updated","date"), author=value(entry,"creator","author"),
                          source_entry_id=identity, enclosures=enclosures, feed_url=url))
        if len(items) >= limit:
            break
    return result(items, feed_url=url, truncated=len(entries)>len(items), total_in_response=len(entries),
                  coverage="Entries in the fetched feed response. Earlier entries may have expired from the feed.")


def read_feed(parameters: dict) -> dict:
    response = fetch(parameters["url"], max_bytes=4*1024*1024)
    return parse_feed(response.content,response.url,parameters["max_items"])
