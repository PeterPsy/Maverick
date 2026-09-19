#!/bin/sh
# Certbot deploy hook for this lineage only; never restart Maverick Core.
set -eu
[ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt/live/maverick-external-apps ] || exit 0
# Initial issuance precedes ingress installation; no reload is needed then.
[ -e /etc/nginx/sites-enabled/maverick-external-apps.conf ] || exit 0
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
