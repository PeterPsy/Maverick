"""Encrypted per-call native evidence, separate from the visible transcript."""

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from uuid import uuid4

from core.runtime.private_payload_models import RuntimePrivatePayloadContext
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.service import record_runtime_event
from core.secrets.key_material import load_secret_store_key, load_secret_store_keyring


class DeviceUseEvidenceArchive:
    def __init__(self, *, store, payload_store):
        self.store = store
        self.payload_store = payload_store

    @classmethod
    def for_repository(cls, store, start_path):
        return cls(store=store, payload_store=EncryptedRuntimePrivatePayloadStore(
            repository_root=start_path, key_loader=load_secret_store_key,
            keyring_loader=load_secret_store_keyring,
        ))

    def capture(self, *, binding, record, arguments=None, result=None, jpeg=None):
        """Persist bounded blobs and only opaque references in runtime events."""
        context = self._context(binding, record.runtime_session_id)
        document = {"journal": asdict(record)}
        if arguments is not None:
            # Typed text can include secrets in Full. Keep it out of the audit
            # projection even for owners; the live executor still gets it.
            document["arguments"] = _audit_arguments(arguments)
        if result is not None:
            document["result"] = result
        image_refs = []
        if jpeg:
            for offset in range(0, len(jpeg), 1_048_576):
                image_refs.append(self._put(context, jpeg[offset:offset + 1_048_576]))
            document["image_refs"] = image_refs
            document["image_sha256"] = hashlib.sha256(jpeg).hexdigest()
            document["image_bytes"] = len(jpeg)
        payload = json.dumps(document, ensure_ascii=False, default=_json_default, separators=(",", ":")).encode()
        ref = self._put(context, payload)
        record_runtime_event(
            self.store, event_id=str(uuid4()), session_id=record.runtime_session_id,
            turn_id=record.turn_id, plane="runtime", event_type="runtime.device_use.evidence",
            payload={"invocation_id": record.invocation_id, "call_id": record.call_id,
                     "turn_id": record.turn_id, "tool_name": record.tool_name,
                     "action": record.action, "status": record.status,
                     "evidence_ref": ref, "has_image": bool(image_refs),
                     "native_duration_ms": record.native_duration_ms,
                     "native_user_wait_ms": record.native_user_wait_ms,
                     "native_success": record.native_success, "result_valid": record.result_valid,
                     "outcome_state": record.outcome_state, "failure_reason_code": record.failure_reason_code,
                     "image_bytes": len(jpeg) if jpeg else 0,
                     "project_stage": _project_stage(result),
                     "bridge_end_to_end_ms": max(0, (record.completed_at - record.dispatched_at).total_seconds() * 1000) if record.completed_at else None},
        )

    def read(self, *, session, ref):
        binding = session.device_use_binding
        if binding is None:
            raise ValueError("device_use_evidence_unavailable")
        return json.loads(self.payload_store.read(
            context=self._context(binding, session.session_id), locator_prefix="device-use",
            private_ref=ref,
        ))

    def image(self, *, session, document):
        refs = document.get("image_refs")
        if not isinstance(refs, list) or not 1 <= len(refs) <= 4:
            raise ValueError("device_use_image_unavailable")
        image = b"".join(self.payload_store.read(
            context=self._context(session.device_use_binding, session.session_id),
            locator_prefix="device-use", private_ref=ref,
        ) for ref in refs)
        if len(image) != document.get("image_bytes") or hashlib.sha256(image).hexdigest() != document.get("image_sha256"):
            raise ValueError("device_use_image_integrity_failed")
        return image

    def _put(self, context, payload):
        return self.payload_store.put(
            context=context, locator_prefix="device-use", payload=payload,
            max_blob_bytes=2 * 1_048_576, max_session_bytes=128 * 1_048_576,
        )

    @staticmethod
    def _context(binding, session_id):
        return RuntimePrivatePayloadContext(
            namespace="device-use-evidence", workspace_id=binding.workspace_id,
            session_id=session_id,
            binding_fields=(("owner_user_id", binding.owner_user_id),),
        )


def _audit_arguments(value):
    if isinstance(value, dict):
        return {key: "[typed text withheld]" if key == "text" else _audit_arguments(child)
                for key, child in value.items()}
    if isinstance(value, list):
        return [_audit_arguments(child) for child in value]
    return value


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("unsupported_evidence_value")


def _project_stage(result):
    try:
        payload = json.loads(result["contentItems"][0]["text"])
        stage = payload["checkpoint"]["state"]["stage"]
        if payload.get("action") == "save_checkpoint" and stage in {
            "planning", "timeline_ready", "export_dialog_open", "export_started", "file_present", "file_verified"
        }:
            return stage
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return None
