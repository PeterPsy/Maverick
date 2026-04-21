"""Command-line wrapper for the Maverick App SDK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.api.platform_state import bootstrap_platform_state
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command


def main(argv: list[str] | None = None) -> int:
    """Run the Maverick CLI wrapper."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.domain != "app":
        parser.error("Only `maverick app ...` is currently supported by this wrapper.")
    repository_root = Path(args.repository_root).resolve() if args.repository_root else None
    state = bootstrap_platform_state(start_path=repository_root)
    context = CliInvocationContext(
        caller_kind="operator",
        workspace_id=args.workspace,
        agent_id=None,
        effective_mode="full-access",
    )
    command_id = f"core.app-sdk.{args.action}"
    result = run_core_cli_command(
        command_id=command_id,
        context=context,
        app_store=state.app_store,
        observability_store=state.observability_store,
        workspace_id=args.workspace,
        start_path=state.repository_root,
        arguments=_arguments(args),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maverick")
    parser.add_argument("--repository-root", default=None)
    subparsers = parser.add_subparsers(dest="domain", required=True)
    app = subparsers.add_parser("app")
    app_subparsers = app.add_subparsers(dest="action", required=True)
    _create_parser(app_subparsers)
    _app_id_parser(app_subparsers, "validate")
    _app_id_parser(app_subparsers, "register-local")
    _app_id_parser(app_subparsers, "install-local")
    _app_id_parser(app_subparsers, "status")
    package = app_subparsers.add_parser("package")
    package.add_argument("--workspace", default="default")
    package.add_argument("--app-root", required=True)
    package.add_argument("--output-path", default=None)
    return parser


def _create_parser(subparsers) -> None:
    create = subparsers.add_parser("create")
    create.add_argument("app_id")
    create.add_argument("--template", dest="template_id", default="minimal")
    create.add_argument("--workspace", default="default")
    create.add_argument("--target-kind", default="workspace_local")
    create.add_argument("--name", default=None)
    create.add_argument("--description", default=None)
    create.add_argument("--publisher", default="workspace")
    create.add_argument("--version", default="0.1.0")
    create.add_argument("--entity", dest="entities", action="append", default=None)
    create.add_argument("--overwrite", action="store_true")


def _app_id_parser(subparsers, action: str) -> None:
    parser = subparsers.add_parser(action)
    parser.add_argument("app_id")
    parser.add_argument("--workspace", default="default")


def _arguments(args) -> dict[str, Any]:
    if args.action == "create":
        return {
            "app_id": args.app_id,
            "template_id": args.template_id,
            "workspace_id": args.workspace,
            "target_kind": args.target_kind,
            "name": args.name,
            "description": args.description,
            "publisher": args.publisher,
            "version": args.version,
            "entities": args.entities,
            "overwrite": args.overwrite,
        }
    if args.action == "package":
        return {"app_root": args.app_root, "output_path": args.output_path}
    return {"app_id": args.app_id, "workspace_id": args.workspace}


if __name__ == "__main__":
    raise SystemExit(main())
