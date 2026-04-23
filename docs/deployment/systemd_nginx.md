# Systemd and Nginx Deployment

This deployment path is for local demos, self-hosted evaluation, and controlled review environments only.

Maverick is not production-ready. Do not expose this configuration with real secrets until the documented security hardening work is closed.

## Files

- `scripts/deploy/systemd/maverick3-core.service`
- `scripts/deploy/systemd/maverick3-rescue.service`
- `scripts/deploy/systemd/maverick3-backend-watchdog.service`
- `scripts/deploy/systemd/maverick3-backend-watchdog.timer`
- `scripts/deploy/nginx/maverick.example.conf`

Run the installer to bootstrap, verify, render, and optionally apply the deployment in one flow:

```bash
python3 scripts/install_maverick.py --hostname maverick.example.com --install-root /opt/maverick-v3
```

In interactive mode the installer asks for missing values, then prompts before:

- writing live systemd units
- writing live nginx config and symlink
- enabling and restarting services
- requesting a TLS certificate with `certbot`

It always renders a copy of the deployment plan under:

- `.maverick/install/systemd/*.service`
- `.maverick/install/systemd/*.timer`
- `.maverick/install/nginx/<hostname>.conf`
- `.maverick/install/install-manifest.json`

Use `--render-only` to stop after rendering.

Use `--systemd-dir` and `--nginx-conf` to customize rendered output paths, and `--live-systemd-dir`, `--live-nginx-conf`, and `--live-nginx-enabled` to customize the live target paths used by apply.

## Minimum Hardening

- bind the core service to `127.0.0.1`
- terminate TLS at nginx
- set upload limits
- keep logs outside the repository
- do not store production secrets in local JSON state
- keep rescue automation disabled unless an operator has reviewed the policy
- restrict filesystem permissions on `.maverick/`, logs, and workspace roots

## Production Status

This is not a production deployment guide. It is a starting point for repeatable demo infrastructure.
