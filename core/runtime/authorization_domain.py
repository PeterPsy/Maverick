"""Explicit authorization domains. Client/model data cannot select a resolver."""

from core.providers.errors import CapabilityCertificateError


def require_production_authorization(value: object) -> None:
    if (getattr(value, "authorization_domain", "production") != "production"
            or getattr(value, "lab_permit_reference", None) is not None
            or getattr(value, "purpose", None) == "certification_lab"):
        raise CapabilityCertificateError("lab_authority_forbidden_in_production")
