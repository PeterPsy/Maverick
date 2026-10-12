"""Change only address-derived environment keys and preserve other settings."""

import re

from core.shared.env_file import quote_env_value

ADDRESS_KEYS = {
    "MAVERICK_SIDECAR_ORIGIN_MODE", "MAVERICK_SIDECAR_INSTALLATION_DOMAIN",
    "MAVERICK_SIDECAR_PLATFORM_ORIGIN", "MAVERICK_BROWSER_ORIGIN_TLS_MODE",
    "MAVERICK_GOOGLE_REDIRECT_URI", "MAVERICK_INSTALLATION_PUBLIC_IP",
}


def address_environment(content: str, values: dict[str, str | None]) -> str:
    if set(values) - ADDRESS_KEYS:
        raise ValueError("Only installation address keys may be changed")
    output, remaining = [], dict(values)
    for line in content.splitlines(keepends=True):
        match = re.match(r"^(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
        key = match.group(1) if match else None
        if key not in values:
            output.append(line)
        elif key in remaining:
            value = remaining.pop(key)
            if value is not None:
                output.append(key + "=" + quote_env_value(value) + "\n")
    if output and not output[-1].endswith("\n"):
        output[-1] += "\n"
    output.extend(key + "=" + quote_env_value(value) + "\n" for key, value in remaining.items() if value is not None)
    return "".join(output)


def target_environment(plan: dict) -> dict:
    return {"MAVERICK_SIDECAR_ORIGIN_MODE": "hosted",
            "MAVERICK_SIDECAR_INSTALLATION_DOMAIN": plan["hostname"],
            "MAVERICK_SIDECAR_PLATFORM_ORIGIN": plan["public_url"],
            "MAVERICK_BROWSER_ORIGIN_TLS_MODE": "external_wildcard",
            "MAVERICK_INSTALLATION_PUBLIC_IP": plan["target_ip"],
            "MAVERICK_GOOGLE_REDIRECT_URI": plan["public_url"] + "/api/auth/google/callback"}
