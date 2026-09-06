"""Installation-owned issuer trust, reloaded rather than supplied by workers."""

import base64
from dataclasses import dataclass
import json
from pathlib import Path

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.permit_codec import _unique_keys
from core.certification_lab.private_files import read_private_file


@dataclass(frozen=True)
class LabPermitTrust:
    path: Path
    installation_id: str

    def public_key(self, *, issuer_key_id: str, authorization_ref: str) -> bytes:
        try:
            policy = json.loads(read_private_file(self.path), object_pairs_hook=_unique_keys)
            if (set(policy) != {"schema", "installation_id", "issuers"}
                    or policy["schema"] != "maverick-lab-issuer-trust.v1"
                    or policy["installation_id"] != self.installation_id):
                raise ValueError
            issuer = policy["issuers"][issuer_key_id]
            if (set(issuer) != {"public_key", "operator_authorization_refs"}
                    or authorization_ref not in issuer["operator_authorization_refs"]
                    or not isinstance(issuer["operator_authorization_refs"], list)):
                raise ValueError
            key = base64.b64decode(issuer["public_key"], validate=True)
            if len(key) != 32:
                raise ValueError
            return key
        except (ValueError, TypeError, KeyError) as error:
            raise LabAuthorizationError("lab_issuer_untrusted") from error
