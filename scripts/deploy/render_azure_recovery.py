"""Render the recovery plan for Maverick's migrated Azure chroot."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


MIGRATION_ROOT = Path("/srv/migration/loopino-root")
HOSTNAME = "maverick.loopino.ai"
SERVICES = ("maverick-core.service", "maverick-rescue.service")
RECOVERY_INCLUDE = "    include /etc/nginx/azure-maverick-recovery.conf;\n"


def _service_identity(migration_root: Path) -> tuple[int, int]:
    for line in (migration_root / "etc/passwd").read_text().splitlines():
        fields = line.split(":")
        if fields[0] == "ubuntu":
            uid, gid = int(fields[2]), int(fields[3])
            if uid <= 0 or gid <= 0:
                raise ValueError("The migrated ubuntu account must be unprivileged.")
            return uid, gid
    raise ValueError("The migrated ubuntu account was not found.")


def _adapt_environment_files(content: str, migration_root: Path) -> str:
    lines = []
    for line in content.splitlines(keepends=True):
        if line.startswith("EnvironmentFile="):
            value = line.removeprefix("EnvironmentFile=").strip()
            optional = "-" if value.startswith("-") else ""
            filename = value.removeprefix("-")
            if filename:
                if not filename.startswith("/") or any(c in filename for c in '%"\' \t'):
                    raise ValueError(f"Unsupported EnvironmentFile path: {filename}")
                line = f"EnvironmentFile={optional}{migration_root}{filename}\n"
        lines.append(line)
    return "".join(lines)


def render_plan(migration_root: Path, repository_root: Path, output_root: Path) -> None:
    migration_root = migration_root.resolve(strict=True)
    if any(c in str(migration_root) for c in '%"\' \t\n'):
        raise ValueError("The migration root must be an absolute path without spaces or specifiers.")
    uid, gid = _service_identity(migration_root)
    operating_group = (migration_root / "home/ubuntu/projects/maverick-v3").stat().st_gid
    nginx_root = migration_root / "etc/nginx"
    runtime = (nginx_root / "azure-runtime.conf").read_text()
    anchor = "    include /etc/nginx/azure-loopino-unified.conf;\n"
    if runtime.count(anchor) != 1:
        raise ValueError("Expected the Azure nginx configuration with one Loopino include.")
    if RECOVERY_INCLUDE not in runtime:
        runtime = runtime.replace(anchor, anchor + RECOVERY_INCLUDE)

    source_systemd = migration_root / "etc/systemd/system"
    output_root.mkdir(parents=True, exist_ok=True)
    systemd_root = output_root / "systemd"
    systemd_root.mkdir(exist_ok=True)
    for service in SERVICES:
        content = (source_systemd / service).read_text()
        (systemd_root / service).write_text(_adapt_environment_files(content, migration_root))
        dropins = systemd_root / f"{service}.d"
        if dropins.exists():
            shutil.rmtree(dropins)
        dropins.mkdir()
        for source in sorted((source_systemd / f"{service}.d").glob("*.conf")):
            (dropins / source.name).write_text(_adapt_environment_files(source.read_text(), migration_root))
        (dropins / "zz-azure-migration.conf").write_text(
            f"[Unit]\nRequiresMountsFor={migration_root}\n"
            f"[Service]\nRootDirectory={migration_root}\nMountAPIVFS=yes\n"
            f"User={uid}\nGroup={gid}\n"
            f"SupplementaryGroups={operating_group}\n"
            "Environment=HOME=/home/ubuntu USER=ubuntu LOGNAME=ubuntu\n"
        )

    templates = repository_root / "scripts/deploy/nginx"
    # Reuse redirect-only HTTP hosts; API traffic stays on HTTPS during ACME.
    http = (templates / "maverick.example.conf").read_text().split("\nserver {", 1)[0] + "\n"
    http += (templates / "maverick.sidecars.managed.http.conf").read_text()
    for key, value in (
        ("{{HOSTNAME}}", HOSTNAME),
        ("{{ACME_ROOT}}", f"/var/www/{HOSTNAME}"),
        ("{{BROWSER_ORIGIN_ACME_WEBROOT}}", "/var/lib/maverick/browser-origin-acme"),
    ):
        http = http.replace(key, value)
    if "{{" in http or "ssl_certificate" in http or "proxy_pass" in http:
        raise ValueError("The ACME phase must contain only HTTP challenges and HTTPS redirects.")
    for filename in (f"{HOSTNAME}.conf", "maverick-sidecars.loopino.ai.conf"):
        if not (nginx_root / "sites-available" / filename).is_file():
            raise ValueError(f"Missing migrated nginx virtual host: {filename}")
    (output_root / "azure-runtime.conf").write_text(runtime)
    (output_root / "http.conf").write_text(http)
    (output_root / "https.conf").write_text(
        f"include /etc/nginx/sites-available/{HOSTNAME}.conf;\n"
        "include /etc/nginx/sites-available/maverick-sidecars.loopino.ai.conf;\n"
    )
    (output_root / "renewal.conf").write_text(
        "[Service]\nExecStart=/usr/bin/certbot renew --quiet --non-interactive "
        f"--cert-name {HOSTNAME} --webroot -w /var/www/{HOSTNAME}\n"
    )


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration-root", type=Path, default=MIGRATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=repository_root / ".maverick/install/azure-recovery")
    args = parser.parse_args()
    render_plan(args.migration_root, repository_root, args.output_root)
    print(f"Recovery plan rendered: {args.output_root}")


if __name__ == "__main__":
    main()
