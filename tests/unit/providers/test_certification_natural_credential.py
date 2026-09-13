from pathlib import Path
import unittest
from unittest.mock import patch

from core.providers.certification_natural_credential import service_environment


class CertificationNaturalCredentialTest(unittest.TestCase):
    def test_service_environment_resolves_only_filesystem_variables(self):
        environ = b"\0".join(
            (
                b"MAVERICK_CONTROL_STORE=mongodb://control.example/maverick",
                b"MAVERICK_JSON_CONTROL_STORE_ROOT=var/control",
                b"MAVERICK_SECRET_KEY_FILE=/run/maverick/key",
                b"MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT=1",
                b"MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW=0",
                b"IGNORED_VARIABLE=relative-value",
            )
        )
        control_root = Path("/srv/maverick")

        with patch(
            "core.providers.certification_natural_credential.subprocess.check_output",
            return_value="123\n",
        ), patch.object(Path, "read_bytes", return_value=environ):
            actual = service_environment(control_root)

        self.assertEqual(
            actual,
            {
                "MAVERICK_CONTROL_STORE": "mongodb://control.example/maverick",
                "MAVERICK_JSON_CONTROL_STORE_ROOT": "/srv/maverick/var/control",
                "MAVERICK_SECRET_KEY_FILE": "/run/maverick/key",
                "MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT": "1",
                "MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW": "0",
            },
        )


if __name__ == "__main__":
    unittest.main()
