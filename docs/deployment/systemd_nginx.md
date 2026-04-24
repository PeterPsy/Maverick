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
cd /opt/maverick-v3
python3 scripts/install_maverick.py --hostname maverick.example.com --install-root /opt/maverick-v3
```

`--install-root` currently must be the checkout root that the installer is running from.
Clone Maverick directly into the intended install root before running the installer.
The installer fails instead of rendering systemd units that point at a different tree from the one it bootstrapped.

In interactive mode the installer asks for missing values, then prompts before:

- writing live systemd units
- writing live nginx config and symlink
- enabling and restarting services
- requesting a TLS certificate with `certbot`

It always renders a copy of the deployment plan under:

- `.maverick/install/systemd/*.service`
- `.maverick/install/systemd/*.timer`
- `.maverick/install/nginx/<hostname>.conf`
- `.maverick/install/maverick3.env`
- `.maverick/install/install-manifest.json`

The generated `maverick3.env` file is loaded by the systemd units through `EnvironmentFile=`.
It contains local bootstrap credentials and signing secrets and is written with mode `0600`.
Keep it out of version control and rotate generated values before any longer-lived public exposure.

Use `--render-only` to stop after rendering.

Use `--systemd-dir`, `--nginx-conf`, and `--install-env` to customize rendered output paths, and `--live-systemd-dir`, `--live-nginx-conf`, and `--live-nginx-enabled` to customize the live target paths used by apply.

Preflight checks are blocking for live apply. Missing systemd, nginx, certbot, Codex, bubblewrap, or frontend build tools fail the installer before live files are written when those tools are required by the selected mode. `--force` exists for reviewed operator exceptions only.

Post-apply health checks are also blocking. If any required health endpoint fails, the installer exits non-zero. Use `--skip-health-check` only when another supervisor is performing the same verification.

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
