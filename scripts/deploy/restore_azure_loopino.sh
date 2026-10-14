#!/usr/bin/env bash
# Restore the existing Loopino installation inside the migrated Azure root.
set -Eeuo pipefail

migration_root=/root/projects/loopino/operations/migration/loopino-root
hostname=loopino.giuntitrail.com
repository_root="$migration_root/projects/loopino"
plan_root="$repository_root/.loopino/install/azure-recovery"
runtime_conf="$migration_root/etc/nginx/azure-runtime.conf"
recovery_conf="$migration_root/etc/nginx/azure-loopino-recovery.conf"
services=(loopino-core.service loopino-rescue.service)

fail() { printf '%s\n' "$*" >&2; exit 1; }
nginx_check() { chroot "$migration_root" /usr/sbin/nginx -t -c /etc/nginx/azure-runtime.conf; }

verify_site() {
    local scope=$1 path host status
    local resolve=()
    [[ "$scope" != local ]] || resolve=(--resolve "$hostname:443:127.0.0.1")
    curl --noproxy '*' --fail --silent --show-error --max-time 20 \
        --retry 3 --retry-delay 1 --retry-all-errors --retry-max-time 20 "${resolve[@]}" \
        "https://$hostname/" --output /dev/null || return 1
    for path in /health /api/session /api/pwa/config; do
        curl --noproxy '*' --fail --silent --show-error --max-time 20 "${resolve[@]}" \
            "https://$hostname$path" | python3 -c '
import json, sys
data = json.load(sys.stdin)
path = sys.argv[1]
if not isinstance(data, dict):
    raise SystemExit("Expected a JSON object")
if path == "/health":
    if data.get("status") != "ok" or data.get("service") != "loopino-core":
        raise SystemExit("Unexpected core health response")
elif path == "/api/session":
    if data.get("authenticated") is not False:
        raise SystemExit("Unexpected anonymous session response")
elif path == "/api/pwa/config":
    if "error" in data:
        raise SystemExit("PWA configuration returned an error")
' "$path" || return 1
        printf '%s: HTTPS + JSON OK (%s)\n' "$path" "$scope"
    done
    for host in "af-000000000000000000000000.sidecars.$hostname" "sc-000000000000000000000000.sidecars.$hostname"; do
        resolve=()
        [[ "$scope" != local ]] || resolve=(--resolve "$host:443:127.0.0.1")
        status=$(curl --noproxy '*' --silent --show-error --max-time 20 "${resolve[@]}" \
            "https://$host/" --output /dev/null --write-out '%{http_code}') || return 1
        [[ "$status" =~ ^[234][0-9][0-9]$ ]] || { printf '%s: HTTP %s\n' "$host" "$status" >&2; return 1; }
        printf '%s: TLS OK (%s)\n' "$host" "$scope"
    done
}

rollback() {
    local code=$1 path restore_failed=0
    trap - ERR INT TERM HUP
    set +e
    if [[ "$services_started" == 1 ]]; then
        systemctl disable --now "${services[@]}" >/dev/null 2>&1 || restore_failed=1
    fi
    for path in "${changed_paths[@]}"; do
        rm -rf -- "$path" || restore_failed=1
        if [[ -e "$backup_root/${path#/}" || -L "$backup_root/${path#/}" ]]; then
            mkdir -p -- "$(dirname "$path")" || restore_failed=1
            cp -a -- "$backup_root/${path#/}" "$path" || restore_failed=1
        fi
    done
    systemctl daemon-reload || restore_failed=1
    if ! nginx_check || ! systemctl reload migrated-nginx.service; then restore_failed=1; fi
    if [[ "$restore_failed" == 0 ]]; then
        printf 'Recovery failed; previous configuration restored. Backup: %s\n' "$backup_root" >&2
    else
        printf 'Recovery failed; automatic rollback needs attention. Backup: %s\n' "$backup_root" >&2
    fi
    exit "$code"
}

apply_plan() {
    [[ "$EUID" == 0 ]] || fail 'Live recovery requires a root terminal on the Azure server.'
    [[ "$(systemctl show --property=RootDirectory --value migrated-nginx.service)" == "$migration_root" ]] \
        || fail 'migrated-nginx is not configured with the expected migration root.'
    systemctl is-active --quiet migrated-nginx.service || fail 'migrated-nginx is not active.'
    local service path operating_group
    for service in "${services[@]}"; do
        [[ "$(systemctl show --property=LoadState --value "$service")" == not-found ]] \
            || fail "$service already exists on this host; inspect it before running first-install recovery."
        [[ ! -e "/etc/systemd/system/$service" && ! -e "/etc/systemd/system/$service.d" ]] \
            || fail "An existing host override for $service needs review."
    done
    [[ -f "$repository_root/.env" ]] || fail 'The migrated Loopino .env is missing.'
    [[ -f "$migration_root/projects/loopino/installation/tls/certbot/config/renewal/$hostname.conf" ]] || fail 'The migrated Loopino Certbot lineage is missing.'
    [[ -d "$migration_root/projects/loopino/data/browser-origin-tls/private" ]] || fail 'The migrated browser-origin private directory is missing.'
    [[ -d "$migration_root/projects/loopino/data/browser-origin-tls/served/hosts" ]] || fail 'The migrated published browser-origin directory is missing.'
    systemctl is-enabled --quiet migration-cert-renewal.timer || fail 'The existing migration certificate renewal timer must be enabled.'
    operating_group=$(stat -c '%g' "$repository_root")
    if ! getent group "$operating_group" >/dev/null; then
        groupadd --gid "$operating_group" loopino-migrated-data
    fi
    chroot "$migration_root" /usr/bin/env \
        LD_LIBRARY_PATH=/root/projects/loopino/.loopino/sqlite/3.51.3/lib \
        /root/projects/loopino/.venv/bin/python -c 'import ssl, sqlite3, uvicorn, cryptography'
    nginx_check
    python3 "$repository_root/scripts/deploy/render_azure_recovery.py"

    # Only root-owned real installation parents may hold recovery snapshots.
    backup_root=$("$repository_root/.venv/bin/python" - "$repository_root" <<'PYBACKUP'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from core.installation.protected_material import create_recovery_backup
from datetime import datetime, timezone
print(create_recovery_backup(Path(sys.argv[1]), "azure", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")))
PYBACKUP
    )
    changed_paths=("$runtime_conf" "$recovery_conf"
        /etc/systemd/system/loopino-core.service /etc/systemd/system/loopino-core.service.d
        /etc/systemd/system/loopino-rescue.service /etc/systemd/system/loopino-rescue.service.d
        /etc/systemd/system/migration-cert-renewal.service.d/loopino.conf)
    for path in "${changed_paths[@]}"; do
        if [[ -e "$path" || -L "$path" ]]; then
            mkdir -p -- "$backup_root/$(dirname "${path#/}")"
            cp -a -- "$path" "$backup_root/${path#/}"
        fi
    done
    printf 'Configuration backup: %s\n' "$backup_root"
    services_started=0
    trap 'rollback "$?"' ERR
    trap 'rollback 130' INT
    trap 'rollback 143' TERM
    trap 'rollback 129' HUP

    # HTTP-01 must be routed before requesting or renewing any certificate.
    mkdir -p "$migration_root/projects/loopino/data/acme-webroot/.well-known/acme-challenge"
    install -m 0644 "$plan_root/http.conf" "$recovery_conf"
    install -m 0644 "$plan_root/azure-runtime.conf" "$runtime_conf"
    nginx_check
    systemctl reload migrated-nginx.service
    chroot "$migration_root" /root/projects/loopino/scripts/deploy/loopino-certbot renew --non-interactive \
        --cert-name "$hostname" --webroot -w /root/projects/loopino/data/acme-webroot \
        --config-dir /root/projects/loopino/installation/tls/certbot/config \
        --work-dir /root/projects/loopino/installation/tls/certbot/work \
        --logs-dir /root/projects/loopino/installation/tls/certbot/logs
    chroot "$migration_root" /usr/bin/openssl x509 \
        -in "/root/projects/loopino/installation/tls/certbot/config/live/$hostname/fullchain.pem" -noout -checkhost "$hostname" -checkend 0
    chroot "$migration_root" /usr/sbin/runuser --user ubuntu -- /bin/sh -c '
        cd /root/projects/loopino
        exec .venv/bin/python -m core.shared.browser_origin_tls \
            --installation-domain loopino.giuntitrail.com \
            --tls-root /root/projects/loopino/data/browser-origin-tls \
            --acme-webroot /root/projects/loopino/data/browser-origin-acme \
            --group-key browser-origin-probes:loopino.giuntitrail.com \
            --host af-000000000000000000000000.sidecars.loopino.giuntitrail.com \
            --host sc-000000000000000000000000.sidecars.loopino.giuntitrail.com
    '

    for service in "${services[@]}"; do
        install -m 0644 "$plan_root/systemd/$service" "/etc/systemd/system/$service"
        cp -a "$plan_root/systemd/$service.d" "/etc/systemd/system/$service.d"
    done
    mkdir -p /etc/systemd/system/migration-cert-renewal.service.d
    install -m 0644 "$plan_root/renewal.conf" /etc/systemd/system/migration-cert-renewal.service.d/loopino.conf
    systemctl daemon-reload
    services_started=1
    systemctl enable --now "${services[@]}"
    curl --noproxy '*' --fail --silent --show-error --max-time 5 \
        --retry 20 --retry-delay 2 --retry-all-errors --retry-max-time 90 \
        http://127.0.0.1:8014/health --output /dev/null

    install -m 0644 "$plan_root/https.conf" "$recovery_conf"
    nginx_check
    systemctl reload migrated-nginx.service
    verify_site local
    trap - ERR INT TERM HUP
    # A public DNS failure must not remove a working local HTTPS recovery.
    if ! verify_site public; then
        printf 'Local HTTPS recovery passed; public DNS/TLS verification failed. Services remain active.\n' >&2
        exit 1
    fi
    printf 'Loopino public HTTPS and APIs verified. Backup: %s\n' "$backup_root"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:---render-only}" in
        --render-only) python3 "$repository_root/scripts/deploy/render_azure_recovery.py" ;;
        --apply) apply_plan ;;
        --verify) verify_site local && verify_site public ;;
        *) fail 'Usage: bash scripts/deploy/restore_azure_loopino.sh [--render-only|--apply|--verify]' ;;
    esac
fi
