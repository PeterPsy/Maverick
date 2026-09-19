"""Non-secret administrative deployment configuration; no arbitrary probe URL."""
import json
from pathlib import Path
from uuid import uuid4

from .errors import AppError
from .files import atomic_write, encoded, read_regular
from .policy import domain_name, identifier


def public_domain(installation_domain):
    """Operator-attested Maverick hostname, never a browser Host/frame origin."""
    import ipaddress
    hostname = domain_name(installation_domain)
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return domain_name("apps." + hostname)
    raise AppError("installation_domain_required")


def load(root: Path):
    try:
        value = json.loads(read_regular(root / "deployment.json", 4096))
        value["domain"] = domain_name(value["domain"])
        if not value["domain"].startswith("apps."):
            raise AppError("deployment_invalid", 503)
        value["installation_domain"] = value["domain"][5:]
        public_domain(value["installation_domain"])
        identifier(value["namespace"], length=12)
        if value.get("version") != 1:
            raise AppError("deployment_invalid", 503)
        return value
    except FileNotFoundError as error:
        raise AppError("deployment_not_configured", 409) from error
    except (ValueError, KeyError, TypeError) as error:
        raise AppError("deployment_invalid", 503) from error


def configure(root, installation_domain, *, has_apps):
    domain = public_domain(installation_domain)
    if (root / "deployment.json").exists():
        current = load(root)
        if current["domain"] == domain:
            return current
        if has_apps:
            raise AppError("domain_change_not_supported", 409)
        namespace = current["namespace"]
    else:
        namespace = uuid4().hex[:12]
    value = {"version": 1, "domain": domain, "namespace": namespace}
    atomic_write(root / "deployment.json", encoded(value))
    return value
