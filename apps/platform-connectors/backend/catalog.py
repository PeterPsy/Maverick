"""Implemented source routes and capability declarations."""

from __future__ import annotations

from urllib.parse import quote, urlencode


SOURCES = [
    {"id":"instagram","name":"Instagram","category":"social","backend":"chrome","operations":["read","profile","collect","search","video"],"home":"https://www.instagram.com/","description":"Profiles, posts and Reels from your shared tab, with frame and audio evidence."},
    {"id":"twitter","name":"X / Twitter","category":"social","backend":"chrome","operations":["read","profile","collect","search","video"],"home":"https://x.com/home/","description":"Posts, threads, profiles and search results from your session."},
    {"id":"reddit","name":"Reddit","category":"social","backend":"chrome","operations":["read","profile","collect","search","video"],"home":"https://www.reddit.com/","description":"Communities, discussions, rendered comments and search."},
    {"id":"facebook","name":"Facebook","category":"social","backend":"chrome","operations":["read","profile","collect","search","video"],"home":"https://www.facebook.com/","description":"Pages, posts, groups and videos accessible from your shared tab."},
    {"id":"linkedin","name":"LinkedIn","category":"social","backend":"chrome","operations":["read","profile","collect","search"],"home":"https://www.linkedin.com/","description":"Profiles, companies, posts and job listings."},
    {"id":"youtube","name":"YouTube","category":"video","backend":"media","operations":["read","search","transcript"],"home":"https://www.youtube.com/","description":"Search, metadata, timed captions and bounded audio transcription."},
    {"id":"rss","name":"RSS / Atom","category":"web","backend":"http","operations":["read","collect"],"home":None,"description":"Feeds, articles and enclosures with refreshable, deduplicated collections."},
    {"id":"web","name":"Web","category":"web","backend":"browser","operations":["read","search"],"home":None,"description":"Public search and page reading through Browser Lab."},
    {"id":"github","name":"GitHub","category":"development","backend":"http","operations":["read","search","profile","collect"],"home":"https://github.com/","description":"Repositories, READMEs, issues, pull requests and profiles through GitHub APIs."},
]
BY_ID = {source["id"]:source for source in SOURCES}
SOCIAL = frozenset(source["id"] for source in SOURCES if source["backend"] == "chrome")


def source_spec(source: str) -> dict:
    if source not in BY_ID:
        raise ValueError("Unknown source.")
    return BY_ID[source]


def search_url(source: str, query: str) -> str:
    routes = {
        "instagram":("https://www.instagram.com/explore/search/keyword/",{"q":query}),
        "twitter":("https://x.com/search/",{"q":query,"f":"live"}),
        "reddit":("https://www.reddit.com/search/",{"q":query,"type":"link"}),
        "facebook":("https://www.facebook.com/search/top/",{"q":query}),
        "linkedin":("https://www.linkedin.com/search/results/all/",{"keywords":query}),
        "youtube":("https://www.youtube.com/results/",{"search_query":query}),
    }
    base, params = routes[source]
    return base + "?" + urlencode(params)


def profile_url(source: str, username: str) -> str:
    slug = quote(username.strip().lstrip("@"), safe="._-")
    bases = {"instagram":"https://www.instagram.com/", "twitter":"https://x.com/",
             "reddit":"https://www.reddit.com/user/", "facebook":"https://www.facebook.com/",
             "linkedin":"https://www.linkedin.com/in/"}
    return bases[source] + slug + "/"


def observed_item(source: str, observation: dict, url: str | None = None) -> dict:
    canonical = url or observation.get("source_url") or observation.get("url") or ""
    return {"source":source,"url":canonical,"title":str(observation.get("title") or "")[:500],
            "text":str(observation.get("text") or observation.get("content") or "")[:100000],
            "observed_at":observation.get("observed_at"),"content_observed":True,
            "images":observation.get("images",[])[:100],"videos":observation.get("videos",[])[:100],
            "links":observation.get("links",[])[:200],"truncated":bool(observation.get("truncated")),
            "provenance":{"backend":"user_shared_chrome" if source in SOCIAL else observation.get("backend","public_source"),
                          "data_class":"personal" if source in SOCIAL or observation.get("backend") == "user_shared_chrome" else "public","trust":"untrusted_source_content"}}
