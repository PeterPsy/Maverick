"""Text normalization and bounded source result envelopes."""

from html.parser import HTMLParser
from urllib.parse import urlsplit

from catalog import observed_item
from store import now


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value) -> str:
    parser = PlainText()
    parser.feed(str(value or "")[:200000])
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())[:100000]


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value[:2048]
    except ValueError:
        pass
    return ""


def item(source, url, title, text="", **extra):
    return observed_item(source, {"url":safe_url(url), "title":title, "text":plain(text), "observed_at":now()}) | extra


def result(items, *, coverage="Observed source response; not a complete archive.", **extra):
    return {"items":items, "coverage":coverage, "observed_at":now(), **extra}
