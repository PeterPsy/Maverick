"""Observe public recursive DNS without forwarding installation credentials."""

import json
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from uuid import uuid4

from core.installation.cloudflare import NoRedirect


def dns_ready(host: str, address: str) -> bool:
    kind = 28 if ":" in address else 1
    for resolver in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
        for name in (host, "af-" + uuid4().hex[:24] + ".sidecars." + host):
            try:
                request = Request(resolver + "?" + urlencode({"name": name, "type": kind}),
                                  headers={"Accept": "application/dns-json"})
                with build_opener(NoRedirect).open(request, timeout=8) as response:
                    payload = json.loads(response.read(65536))
                answers = {item["data"] for item in payload.get("Answer", []) if item["type"] == kind}
                if answers != {address}:
                    return False
            except (OSError, ValueError, KeyError):
                return False
    return True
