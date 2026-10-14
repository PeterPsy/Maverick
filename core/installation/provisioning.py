"""Narrow ownership handoff for mutable service material in a clean install."""

from pathlib import Path

from core.installation.protected_material import prepare_host_logs, protect_service_environment


def provision_service_paths(config, rendered_files: dict[Path, str], runner) -> None:
    root = config.install_root

    def owned_path(value: str) -> Path:
        path = Path(value)
        path = path if path.is_absolute() else root / path
        if not path.is_relative_to(root) or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Service material must use real paths within the installation")
        mutable_roots = [root / name for name in ("data", "workspaces", "logs", ".cache", ".loopino/installation")]
        if not any(path.is_relative_to(base) for base in mutable_roots) or path.is_relative_to(root / "data/app-artifacts"):
            raise ValueError("Protected installation material cannot be handed to the service")
        return path

    protect_service_environment(config.install_env_path, config.service_group, runner)
    prepare_host_logs(root)
    secret_root = owned_path(config.bootstrap_secret_store_root)
    key = owned_path(config.secret_key_file)
    directories = [
        root / ".loopino/installation", root / "workspaces",
        root / "logs/platform", root / "logs/runtime", root / ".cache", root / ".cache/tmp",
        root / "data/service-home", root / "data/provider-auth", root / "data/provider-auth/codex",
        root / "data/provider-auth/antigravity", root / "data/runtime", secret_root, key.parent,
    ]
    if config.control_store == "json":
        directories.append(owned_path(config.json_control_store_root))
    for directory in dict.fromkeys(directories):
        owned_path(str(directory))
        runner(["install", "-d", "-o", config.service_user, "-g", config.service_group, "-m", "0700", str(directory)])
    for path in rendered_files:
        if path == key or path.is_relative_to(secret_root):
            owned_path(str(path))
            runner(["chown", f"{config.service_user}:{config.service_group}", str(path)])
            runner(["chmod", "0600", str(path)])
