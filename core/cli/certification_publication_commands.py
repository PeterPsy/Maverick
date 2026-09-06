"""Operator-only publication from a publisher-owned archive and trust policy."""

from core.cli.core_command_helpers import OPERATOR_ONLY, core_cli_command, record_cli_audit
from core.providers.certification_live_receipt import decode_certification_json
from core.providers.certification_publication import CertificationPublicationAuthority, CertificationReview
from core.providers.certification_records import signed_run_from_json
from core.providers.errors import CapabilityCertificateError, ProviderError
from core.providers.evidence_store import CapabilityEvidenceBlobStore
from core.providers.google_agentic_certification import publish_google_preview_certificate
from core.providers.openrouter_agentic_certification import publish_openrouter_preview_certificate
from core.shared.repository import discover_repository_root


def certification_publication_command_specs(*, provider_store=None, provider_registry=None,
                                          observability_store=None, start_path=None):
    command_id = "core.providers.agentic.certification.publish"

    def publish(arguments, context):
        # Keep the check at the handler as well as in the official runner.
        if context.caller_kind != "operator" or not context.user_id:
            return {"command_id": command_id, "error": "certification_operator_required"}
        if arguments.get("confirmation") != "reviewed-candidate-certificate-only":
            return {"command_id": command_id, "error": "certification_publication_confirmation_required"}
        if provider_store is None or provider_registry is None:
            return {"command_id": command_id, "error": "certification_publisher_unavailable"}
        try:
            # No worker-supplied path or key map. These are installation-owned
            # files, excluded from tenant mounts and provisioned by the operator.
            root = discover_repository_root(start_path)
            publisher_root = root / "data" / "certification-publisher"
            archive = CapabilityEvidenceBlobStore(publisher_root / "evidence")
            publisher = CertificationPublicationAuthority(
                trust_policy_path=publisher_root / "trust.json", evidence_store=archive,
            )
            signed = signed_run_from_json(archive.get(arguments["signed_run_ref"]).decode("utf-8"))
            review = CertificationReview(**decode_certification_json(archive.get(arguments["review_ref"])))
            profile = provider_store.get_agentic_profile_definition(arguments["definition_id"], arguments["definition_revision"])
            publishers = {"google-ai-studio": publish_google_preview_certificate,
                          "openrouter": publish_openrouter_preview_certificate}
            publish_profile = publishers.get(profile.model_provider_id)
            if publish_profile is None or profile.execution_family != "maverick_agent":
                raise CapabilityCertificateError("certification_target_unsupported")
            certificate = publish_profile(
                provider_store, definition=profile,
                adapter=provider_registry.get_agentic_runtime_adapter(profile.runtime_engine_id),
                signed_run=signed, publisher=publisher, review=review,
            )
        except ProviderError as error:
            return {"command_id": command_id, "error": str(getattr(error, "reason_code", None) or error)}
        except (KeyError, TypeError, ValueError, UnicodeError):
            return {"command_id": command_id, "error": "certification_artifact_invalid"}
        result = {"certificate_id": certificate.certificate_id, "evidence_digest": certificate.evidence_digest,
                  "target_digest": certificate.certification_target_digest, "release_enabled": False}
        record_cli_audit(observability_store, action=command_id, detail="Published reviewed candidate certificate; no release enabled.",
                         payload={**result, "actor_id": context.user_id})
        return {"command_id": command_id, **result}

    properties = {field: {"type": "string", "minLength": 1} for field in (
        "definition_id", "definition_revision", "signed_run_ref", "review_ref",
    )}
    properties["confirmation"] = {"type": "string", "enum": ["reviewed-candidate-certificate-only"]}
    definition = core_cli_command(
        command_id=command_id, path_segments=command_id.split("."), owner_id="providers",
        description="Publish an exact API candidate certificate after retained-evidence and independent-review verification; never enable release.",
        invocation_policy=OPERATOR_ONLY, effect_class="mutating",
        argument_schema={"type": "object", "properties": properties,
                         "required": list(properties), "additionalProperties": False},
    )
    return [(definition, publish)]
