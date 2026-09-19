"""Certificate intent, not serving authority; only validated catalog names."""
import re

from .bindings import read_binding
from .policy import MAX_APPS


def requested_hosts(store, namespace, domain):
    ready = store.ready_app_ids()
    hosts = []
    pattern = re.compile(r"[a-z0-9][a-z0-9-]{0,24}-" + namespace + r"[a-f0-9]{20}\." + re.escape(domain))
    for app in store.list("apps", limit=MAX_APPS):
        binding = read_binding(store.root / "public", app["public_id"])
        if (not binding["archived"] and (binding["current"] or app["id"] in ready)
                and pattern.fullmatch(app["hostname"])):
            hosts.append(app["hostname"])
    return sorted(set(hosts))
