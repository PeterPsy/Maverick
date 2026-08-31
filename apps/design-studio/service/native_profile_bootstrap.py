"""Bootstrap OpenDesign onto an available Maverick native model profile."""

from __future__ import annotations

from typing import Any, Protocol

from official_opendesign_release import OfficialReleaseError


CLOUD_AGENT_ID = "amr"


class OfficialAppConfigClient(Protocol):
    def get_json(self, path: str) -> dict[str, Any]: ...

    def send_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class NativeProfileBootstrap:
    """Run the supported app-config bootstrap once per official process."""

    def __init__(
        self,
        client: OfficialAppConfigClient,
        *,
        preferred_profile_id: str | None,
    ) -> None:
        self._client = client
        self._preferred_profile_id = preferred_profile_id
        self._complete = False

    def ensure(self) -> bool:
        if self._complete or self._preferred_profile_id is None:
            return True
        bootstrap_native_profile(
            self._client,
            preferred_profile_id=self._preferred_profile_id,
        )
        self._complete = True
        return True


def bootstrap_native_profile(
    client: OfficialAppConfigClient,
    *,
    preferred_profile_id: str,
) -> bool:
    """Replace only an unset or unusable cloud selection through public APIs.

    OpenDesign 0.21 recommends its AMR cloud agent during onboarding. The
    Maverick sidecar intentionally exposes no Vela binary or cloud identity;
    it exposes supported local profiles instead. Explicit non-cloud choices
    are preserved.
    """
    if not preferred_profile_id or "\x00" in preferred_profile_id:
        raise OfficialReleaseError("native profile bootstrap identity is invalid")

    config_payload = client.get_json("/api/app-config")
    config = config_payload.get("config")
    if not isinstance(config, dict):
        raise OfficialReleaseError("official OpenDesign app config is invalid")

    selected = config.get("agentId")
    if selected not in {None, "", CLOUD_AGENT_ID}:
        return False

    updated = {
        **config,
        "agentId": preferred_profile_id,
        "onboardingCompleted": True,
    }
    response = client.send_json("PUT", "/api/app-config", updated)
    persisted = response.get("config")
    if (
        not isinstance(persisted, dict)
        or persisted.get("agentId") != preferred_profile_id
        or persisted.get("onboardingCompleted") is not True
    ):
        raise OfficialReleaseError(
            "official OpenDesign did not persist the native profile bootstrap"
        )
    return True


def preferred_profile_id(model_status: dict[str, Any]) -> str | None:
    """Return the primary usable profile emitted by the model bridge."""
    profiles = model_status.get("profiles")
    if not isinstance(profiles, dict):
        return None
    for key in ("profile_id", "api_profile_id"):
        value = profiles.get(key)
        if isinstance(value, str) and value and "\x00" not in value:
            return value
    return None


__all__ = [
    "NativeProfileBootstrap",
    "bootstrap_native_profile",
    "preferred_profile_id",
]
