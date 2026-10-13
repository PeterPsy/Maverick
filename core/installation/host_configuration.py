"""Root-owned nginx staging and selective environment commit/rollback."""

import json
from hashlib import sha256
from pathlib import Path

from core.installation.environment import ADDRESS_KEYS, address_environment, target_environment
from core.installation.errors import InstallationError
from core.installation.validation import record_id, hostname
from core.installation.private_state import write_private
from core.shared.env_file import read_env_file
from scripts.deploy.activate_browser_origin_wildcard import atomic_replace
from scripts.deploy.reload_nginx import check_nginx, reload_nginx


def render_nginx(host: str, certificates: dict, port: int) -> str:
    blocks = []
    for kind, name in [("main", host), ("apps", "*.sidecars." + host)]:
        pair = certificates[kind]
        blocks.append(f'''server {{
    listen 80;
    listen [::]:80;
    server_name {name};
    location / {{ return 301 https://$host$request_uri; }}
}}
server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {name};
    ssl_certificate {pair['fullchain']};
    ssl_certificate_key {pair['private_key']};
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 40m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_hide_header X-Frame-Options;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }}
}}
''')
    return "\n".join(blocks)


def managed_nginx_path(service, host: str) -> Path:
    identifier = record_id(service.configuration()["installation_id"])
    suffix = sha256(hostname(host).encode()).hexdigest()[:16]
    return Path(f"/etc/nginx/conf.d/maverick-installation-{identifier}-{suffix}.conf")


def stage_host(service, plan: dict, certificates: dict, private: Path) -> dict:
    configuration = service.configuration()
    identifier = configuration["installation_id"]
    if identifier == "uninitialized":
        raise InstallationError("installation_worker_not_initialized", status=409)
    path = managed_nginx_path(service, plan["hostname"])
    backup = private / "nginx-before"
    existed = path.exists()
    if not (private / "nginx-backup.json").exists():
        backup.write_bytes(path.read_bytes() if existed else b"")
        backup.chmod(0o600)
        write_private(private / "nginx-backup.json", {"existed": existed, "hostname": plan["hostname"]})
    content = render_nginx(plan["hostname"], certificates, int(service.environment.get("MAVERICK_PORT", "8014")))
    if not path.exists():
        path.touch(mode=0o644)
    try:
        atomic_replace(path, content.encode())
        check_nginx()
        reload_nginx()
    except BaseException:
        if existed:
            atomic_replace(path, backup.read_bytes())
        else:
            path.unlink(missing_ok=True)
        reload_nginx()
        raise
    return {"nginx_changed": True, "nginx_path": str(path)}


def commit_environment(service, plan: dict, private: Path) -> bool:
    path = service.store.repository_root / ".env"
    before = read_env_file(path)
    snapshot = private / "environment-before.json"
    if not snapshot.exists():
        write_private(snapshot, {key: before.get(key) for key in ADDRESS_KEYS})
    original = path.read_text()
    updated = address_environment(original, target_environment(plan))
    if original == updated:
        return False
    atomic_replace(path, updated.encode())
    return True


def restore_host(service, private: Path) -> None:
    metadata = private / "nginx-backup.json"
    if metadata.exists():
        snapshot = json.loads(metadata.read_text())
        path = managed_nginx_path(service, snapshot["hostname"])
        if snapshot["existed"]:
            atomic_replace(path, (private / "nginx-before").read_bytes())
        else:
            path.unlink(missing_ok=True)
        check_nginx()
        reload_nginx()
    snapshot = private / "environment-before.json"
    if snapshot.exists():
        path = service.store.repository_root / ".env"
        atomic_replace(path, address_environment(path.read_text(), json.loads(snapshot.read_text())).encode())
