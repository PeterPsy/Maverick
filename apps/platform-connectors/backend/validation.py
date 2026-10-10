"""Bounded operation inputs; actor, policy and credentials are never caller fields."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from catalog import SOCIAL, source_spec
from http_client import public_target


SOURCE_HOSTS = {
    "instagram":{"www.instagram.com"},"twitter":{"x.com","www.x.com","twitter.com","www.twitter.com"},
    "reddit":{"www.reddit.com","reddit.com"},"facebook":{"www.facebook.com"},"linkedin":{"www.linkedin.com"},
    "youtube":{"www.youtube.com","youtube.com","youtu.be"},"github":{"github.com"},
}
PARAMETERS = frozenset({"url","query","username","session_id","max_items","max_batches","read_details","max_details",
                        "include_reels","frame_count","max_seconds","include_audio","language","kind","collection_id"})


def text(value, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 for c in value):
        raise ValueError(f"{field}: invalid text (maximum {maximum} characters).")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{field}: a value is required.")
    return result


def integer(value, field: str, low: int, high: int) -> int:
    if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
        raise ValueError(f"{field}: an integer is required between {low} and {high}.")
    return value


def parameters(source: str, operation: str, body: dict) -> dict:
    spec = source_spec(source)
    if operation not in spec["operations"]:
        raise ValueError("This operation is unavailable for the selected source.")
    if not isinstance(body,dict) or set(body)-PARAMETERS:
        raise ValueError("Unknown operation parameters.")
    result = dict(body)
    for field,maximum in (("url",2048),("query",500),("username",100),("session_id",80),("language",20),("kind",20),("collection_id",80)):
        if field in result:
            result[field] = text(result[field],field,maximum)
    for field,low,high,default in (("max_items",1,200,30),("max_batches",1,40,12),("max_details",0,200,30),
                                    ("frame_count",1,12,6),("max_seconds",1,180,90)):
        result[field] = integer(result.get(field,default),field,low,high)
    for field,default in (("read_details",True),("include_reels",True),("include_audio",True)):
        result[field] = result.get(field,default)
        if not isinstance(result[field],bool):
            raise ValueError(f"{field}: a boolean is required.")
    if result.get("url"):
        public_target(result["url"],SOURCE_HOSTS.get(source))
        if urlsplit(result["url"]).scheme != "https" and source not in {"rss","web"}:
            raise ValueError("This source requires HTTPS.")
        if source == "youtube":
            parsed = urlsplit(result["url"])
            if parsed.hostname == "youtu.be":
                valid = re.fullmatch(r"/[\w-]{11}/?",parsed.path)
            elif parsed.path.rstrip("/") == "/watch":
                valid = re.fullmatch(r"[\w-]{11}",parse_qs(parsed.query).get("v",[""])[0])
            else:
                valid = re.fullmatch(r"/shorts/[\w-]{11}/?",parsed.path)
            if not valid:
                raise ValueError("Use a YouTube watch, Shorts, or youtu.be video URL.")
    if operation == "search" and not result.get("query"):
        raise ValueError("Enter a search query.")
    if operation == "profile" and not result.get("username") and not result.get("url"):
        raise ValueError("Enter a profile or its URL.")
    if source in SOCIAL:
        if not result.get("session_id") or not re.fullmatch(r"chrome-[a-f0-9-]{36}",result["session_id"]):
            raise ValueError("Select a shared Chrome tab for this platform.")
    elif result.get("session_id"):
        if source != "youtube" or not re.fullmatch(r"chrome-[a-f0-9-]{36}",result["session_id"]):
            raise ValueError("This source does not accept that shared Chrome tab.")
    if source not in SOCIAL and operation in {"read","collect","transcript"} and not result.get("url"):
        raise ValueError("Enter a source URL.")
    return result
