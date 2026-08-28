"""Discovery-first Core wrappers over the authoritative CLI and MCP registries."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

from core.cli.errors import CliInvocationNotAllowedError
from core.cli.runner import CliRunner, _enforce_invocation_policy
from core.egress.classification import fail_closed_classification
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.runner import McpRunner, enforce_mcp_invocation_policy
from core.runtime.tool_catalog import RuntimeCoreCapabilitySurface, RuntimeToolSurfaceResult
from core.runtime.tool_discovery_support import (
    CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT,
    MAX_DISCOVERY_RESULTS,
    call_schema as _call_schema,
    cli_context as _cli_context,
    digest as _digest,
    discovery_classification as _discovery_classification,
    discovery_surface as _surface,
    list_schema as _list_schema,
    mcp_context as _mcp_context,
    registry_revision as _registry_revision,
    required_string as _required_string,
)
from core.runtime.tool_errors import RuntimeToolError


_DISCOVERY_TOKEN_KEY = secrets.token_bytes(32)
_DISCOVERY_TOKEN_DOMAIN = b"maverick.runtime-tool-discovery.v1\0"


class RuntimeToolDiscoveryBroker:
    """Issue turn-local tokens that prove a command/tool was discovered first."""

    def __init__(
        self,
        *,
        cli_registry,
        mcp_registry,
        result_classification_resolver=None,
    ) -> None:
        self.cli_registry = cli_registry
        self.mcp_registry = mcp_registry
        self.cli_runner = CliRunner(cli_registry)
        self.mcp_runner = McpRunner(mcp_registry)
        self.revision = _registry_revision(cli_registry, mcp_registry)
        self.result_classification_resolver = result_classification_resolver

    def list_cli(self, arguments, context, _idempotency_key):
        invocation_context = _cli_context(context)
        definitions = []
        for item in self.cli_registry.list_commands():
            try:
                _enforce_invocation_policy(item.invocation_policy, invocation_context)
            except CliInvocationNotAllowedError:
                continue
            definitions.append(item)
        page, next_cursor = self._page(definitions, arguments)
        payload = {
            "registry_revision": self.revision,
            "commands": [
                {
                    "command_id": item.command_id,
                    "description": item.description[:1024],
                    "argument_schema": item.argument_schema,
                    "effect_class": item.effect_class,
                    "owner_kind": item.owner_kind,
                    "owner_id": item.owner_id,
                    "invocation_token": self._token(
                        "cli",
                        item.command_id,
                        context.session_id,
                    ),
                }
                for item in page
            ],
            "next_cursor": next_cursor,
            "discovery_first": True,
        }
        classification = (
            self._result_classification(
                "core-capability:cli.list",
                arguments,
                payload,
                context,
                source_ref="core:cli-discovery",
            )
            if self.result_classification_resolver is not None
            else _discovery_classification(
                payload,
                source_ref="core:cli-discovery",
                revision=self.revision,
                public=all(
                    item.owner_kind == "core"
                    and item.schema_public
                    and item.certified_tcb_component
                    == CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT
                    for item in page
                ),
            )
        )
        return RuntimeToolSurfaceResult(payload, classification)

    def run_cli(self, arguments, context, idempotency_key):
        command_id = _required_string(arguments.get("command_id"))
        self._validate_token(
            arguments.get("invocation_token"),
            kind="cli",
            target=command_id,
            session_id=context.session_id,
        )
        command_arguments = arguments.get("arguments", {})
        if not isinstance(command_arguments, dict):
            raise RuntimeToolError("tool_arguments_invalid")
        invocation_context = _cli_context(context, idempotency_key=idempotency_key)
        try:
            result = self.cli_runner.run_command(
                command_id=command_id,
                arguments=command_arguments,
                context=invocation_context,
            )
        except CliInvocationNotAllowedError as error:
            raise RuntimeToolError("cli_invocation_denied") from error
        except Exception as error:
            raise RuntimeToolError("cli_invocation_failed") from error
        if not isinstance(result, dict):
            raise RuntimeToolError("tool_result_invalid")
        return RuntimeToolSurfaceResult(
            result,
            self._result_classification(
                "core-capability:cli.run",
                arguments,
                result,
                context,
                source_ref=f"cli:{command_id}",
            ),
        )

    def list_mcp(self, arguments, context, _idempotency_key):
        invocation_context = _mcp_context(context)
        definitions = []
        for item in self.mcp_registry.list_tools():
            try:
                enforce_mcp_invocation_policy(item.invocation_policy, invocation_context)
            except McpInvocationNotAllowedError:
                continue
            definitions.append(item)
        page, next_cursor = self._page(definitions, arguments)
        payload = {
            "registry_revision": self.revision,
            "tools": [
                {
                    "tool_name": item.tool_name,
                    "description": item.description[:1024],
                    "input_schema": item.input_schema,
                    "output_schema": item.output_schema,
                    "effect_class": item.effect_class,
                    "owner_kind": item.owner_kind,
                    "owner_id": item.owner_id,
                    "invocation_token": self._token(
                        "mcp",
                        item.tool_name,
                        context.session_id,
                    ),
                }
                for item in page
            ],
            "next_cursor": next_cursor,
            "discovery_first": True,
        }
        classification = (
            self._result_classification(
                "core-capability:mcp.list",
                arguments,
                payload,
                context,
                source_ref="core:mcp-discovery",
            )
            if self.result_classification_resolver is not None
            else _discovery_classification(
                payload,
                source_ref="core:mcp-discovery",
                revision=self.revision,
                public=all(
                    item.owner_kind == "core"
                    and item.schema_public
                    and item.certified_tcb_component
                    == CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT
                    for item in page
                ),
            )
        )
        return RuntimeToolSurfaceResult(payload, classification)

    def call_mcp(self, arguments, context, idempotency_key):
        tool_name = _required_string(arguments.get("tool_name"))
        self._validate_token(
            arguments.get("invocation_token"),
            kind="mcp",
            target=tool_name,
            session_id=context.session_id,
        )
        tool_arguments = arguments.get("arguments", {})
        if not isinstance(tool_arguments, dict):
            raise RuntimeToolError("tool_arguments_invalid")
        try:
            result = self.mcp_runner.call_tool(
                tool_name=tool_name,
                arguments=tool_arguments,
                context=_mcp_context(context, idempotency_key=idempotency_key),
            )
        except McpInvocationNotAllowedError as error:
            raise RuntimeToolError("mcp_invocation_denied") from error
        except Exception as error:
            raise RuntimeToolError("mcp_invocation_failed") from error
        if not isinstance(result, dict):
            raise RuntimeToolError("tool_result_invalid")
        return RuntimeToolSurfaceResult(
            result,
            self._result_classification(
                "core-capability:mcp.call",
                arguments,
                result,
                context,
                source_ref=f"mcp:{tool_name}",
            ),
        )

    def _result_classification(
        self,
        handle,
        arguments,
        result,
        context,
        *,
        source_ref,
    ):
        if self.result_classification_resolver is not None:
            return self.result_classification_resolver(
                handle,
                arguments,
                result,
                context,
            )
        return fail_closed_classification(
            provenance="tool_result",
            source_ref=source_ref,
            source_revision=self.revision,
            source_digest=_digest(result),
            resource_identity=f"{source_ref}:{context.session_id}",
        )

    def _token(self, kind: str, target: str, session_id: str) -> str:
        raw = json.dumps(
            {
                "kind": kind,
                "target": target,
                "session_id": session_id,
                "registry_revision": self.revision,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(
            _DISCOVERY_TOKEN_KEY,
            _DISCOVERY_TOKEN_DOMAIN + raw,
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(signature + raw).decode("ascii").rstrip("=")

    def _validate_token(
        self,
        value: object,
        *,
        kind: str,
        target: str,
        session_id: str,
    ) -> None:
        if not isinstance(value, str) or not value:
            raise RuntimeToolError("tool_discovery_required")
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            signature, raw = decoded[:32], decoded[32:]
            expected_signature = hmac.new(
                _DISCOVERY_TOKEN_KEY,
                _DISCOVERY_TOKEN_DOMAIN + raw,
                hashlib.sha256,
            ).digest()
            payload = json.loads(raw)
        except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeToolError("tool_discovery_token_invalid") from error
        if (
            not hmac.compare_digest(signature, expected_signature)
            or payload
            != {
                "kind": kind,
                "target": target,
                "session_id": session_id,
                "registry_revision": self.revision,
            }
        ):
            raise RuntimeToolError("tool_discovery_token_invalid")

    @staticmethod
    def _page(definitions: list[object], arguments: dict[str, object]):
        cursor = arguments.get("cursor", 0)
        max_results = arguments.get("max_results", MAX_DISCOVERY_RESULTS)
        if (
            not isinstance(cursor, int)
            or isinstance(cursor, bool)
            or cursor < 0
            or not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= MAX_DISCOVERY_RESULTS
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        page = definitions[cursor : cursor + max_results]
        next_offset = cursor + len(page)
        return page, (next_offset if next_offset < len(definitions) else None)


def build_discovery_first_capabilities(
    *,
    cli_registry,
    mcp_registry,
    result_classification_resolver=None,
) -> tuple[RuntimeCoreCapabilitySurface, ...]:
    broker = RuntimeToolDiscoveryBroker(
        cli_registry=cli_registry,
        mcp_registry=mcp_registry,
        result_classification_resolver=result_classification_resolver,
    )
    return (
        _surface("cli.list", "Discover authorized Core and app CLI commands.", _list_schema(), "read", broker.list_cli),
        _surface("cli.run", "Run one previously discovered CLI command.", _call_schema("command_id"), "destructive", broker.run_cli),
        _surface("mcp.list", "Discover authorized Core and app MCP tools.", _list_schema(), "read", broker.list_mcp),
        _surface("mcp.call", "Call one previously discovered MCP tool.", _call_schema("tool_name"), "destructive", broker.call_mcp),
    )
