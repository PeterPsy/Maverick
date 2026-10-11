// Generated from platforms.json by the Companion build.
export const platforms={
  "instagram": {
    "label": "Instagram",
    "hosts": [
      "www.instagram.com"
    ],
    "paths": [
      "/",
      "/[A-Za-z0-9._]{1,30}/?",
      "/(p|reel)/[A-Za-z0-9_-]{1,80}/?",
      "/[A-Za-z0-9._]{1,30}/reels/?",
      "/explore/tags/[^/]+/?",
      "/explore/search/keyword/?"
    ],
    "query_keys": [
      "q"
    ]
  },
  "twitter": {
    "label": "X / Twitter",
    "hosts": [
      "x.com",
      "www.x.com",
      "twitter.com",
      "www.twitter.com"
    ],
    "paths": [
      "/",
      "/search/?",
      "/home/?",
      "/[A-Za-z0-9_]{1,15}/?",
      "/[A-Za-z0-9_]{1,15}/(with_replies|media)/?",
      "/[A-Za-z0-9_]{1,15}/status/[0-9]+/?",
      "/i/article/[0-9]+/?"
    ],
    "query_keys": [
      "q",
      "f"
    ]
  },
  "reddit": {
    "label": "Reddit",
    "hosts": [
      "www.reddit.com",
      "reddit.com"
    ],
    "paths": [
      "/",
      "/search/?",
      "/r/[A-Za-z0-9_]+/?",
      "/r/[A-Za-z0-9_]+/(hot|new|top|search)/?",
      "/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+(/[^/]+){0,2}/?",
      "/user/[A-Za-z0-9_-]+(/(submitted|comments))?/?",
      "/comments/[A-Za-z0-9]+(/[^/]+){0,2}/?"
    ],
    "query_keys": [
      "q",
      "type",
      "sort",
      "t",
      "restrict_sr"
    ]
  },
  "facebook": {
    "label": "Facebook",
    "hosts": [
      "www.facebook.com"
    ],
    "paths": [
      "/",
      "/search/(top|posts|people|groups|pages|videos)/?",
      "/groups/[A-Za-z0-9._-]+(/posts/[0-9]+)?/?",
      "/reel/[0-9]+/?",
      "/watch/?",
      "/profile.php",
      "/[A-Za-z0-9._-]+(/(posts|videos)/[A-Za-z0-9._-]+)?/?"
    ],
    "query_keys": [
      "q",
      "id",
      "v"
    ]
  },
  "linkedin": {
    "label": "LinkedIn",
    "hosts": [
      "www.linkedin.com"
    ],
    "paths": [
      "/",
      "/feed/?",
      "/in/[^/]+/?",
      "/company/[^/]+(/posts)?/?",
      "/posts/[^/]+/?",
      "/feed/update/[^/]+/?",
      "/search/results/(all|people|content|companies)/?",
      "/jobs/search/?",
      "/jobs/view/[^/]+/?"
    ],
    "query_keys": [
      "keywords",
      "location"
    ]
  },
  "youtube": {
    "label": "YouTube",
    "hosts": [
      "www.youtube.com",
      "youtube.com",
      "youtu.be"
    ],
    "paths": [
      "/",
      "/watch/?",
      "/results/?",
      "/shorts/[A-Za-z0-9_-]+/?",
      "/@[^/]+(/(videos|shorts))?/?",
      "/[A-Za-z0-9_-]{11}/?"
    ],
    "query_keys": [
      "v",
      "search_query"
    ]
  }
}
;
