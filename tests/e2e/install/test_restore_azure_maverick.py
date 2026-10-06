"""Recovery verification must reject transport failures and unrelated backends."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class AzureRecoveryVerificationTestCase(unittest.TestCase):
    def run_verification(self, curl_function: str) -> list[str]:
        repository = Path(__file__).resolve().parents[3]
        script = repository / "scripts/deploy/restore_azure_maverick.sh"
        with tempfile.TemporaryDirectory(prefix="maverick-azure-verify-") as directory:
            calls = Path(directory) / "curl-calls"
            result = subprocess.run(
                [
                    "bash", "-c",
                    'source "$1"\ncurl_calls=$2\n' + curl_function
                    + '\nif verify_site public; then exit 91; fi\n',
                    "verification-test", str(script), str(calls),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return calls.read_text().splitlines()

    def test_failed_https_root_request_cannot_be_hidden_by_later_successful_requests(self) -> None:
        calls = self.run_verification(
            'curl() { printf "%s\\n" "$*" >> "$curl_calls"; return 60; }'
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("https://maverick.loopino.ai/", calls[0])
        self.assertNotIn("/api/session", calls[0])

    def test_http_200_health_from_another_site_is_rejected(self) -> None:
        calls = self.run_verification(
            '''curl() {
                printf '%s\\n' "$*" >> "$curl_calls"
                case "$*" in
                    *https://maverick.loopino.ai/health*)
                        printf '%s\\n' '{"status":"ok","service":"loopino-backend"}' ;;
                esac
                return 0
            }'''
        )
        self.assertEqual(len(calls), 2)
        self.assertIn("/health", calls[-1])


if __name__ == "__main__":
    unittest.main()
