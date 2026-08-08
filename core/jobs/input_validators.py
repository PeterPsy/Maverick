"""Trusted immutable input-grant validation registry."""

from __future__ import annotations

from typing import Callable

from core.jobs.errors import JobValidationError
from core.jobs.models import JobInputGrant, JobSpec, require_identifier


JobInputGrantValidator = Callable[[JobSpec, JobInputGrant], bool]


class JobInputGrantValidatorRegistry:
    """Validate input metadata through its declared provider interface."""

    def __init__(self) -> None:
        self._validators: dict[str, JobInputGrantValidator] = {}

    def register(self, provider_interface: str, validator: JobInputGrantValidator) -> None:
        interface_id = require_identifier(provider_interface, "input_validator.provider_interface")
        if interface_id in self._validators:
            raise JobValidationError(f"Input validator `{interface_id}` is already registered.")
        if not callable(validator):
            raise JobValidationError("Input grant validator must be callable.")
        self._validators[interface_id] = validator

    def validate(self, spec: JobSpec) -> None:
        for grant in spec.input_grants:
            validator = self._validators.get(grant.provider_interface)
            if validator is None:
                raise JobValidationError(
                    f"No trusted input validator is registered for `{grant.provider_interface}`."
                )
            if validator(spec, grant) is not True:
                raise JobValidationError(f"Input grant `{grant.grant_id}` could not be verified.")
