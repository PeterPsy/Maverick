# Systemd and Nginx Deployment

This deployment path is for local demos, self-hosted evaluation, and controlled review environments only.

Maverick is not production-ready. Do not expose this configuration with real secrets until the documented security hardening work is closed.

## Files

- `scripts/deploy/systemd/maverick-core.service`
- `scripts/deploy/systemd/maverick-rescue.service`
- `scripts/deploy/systemd/maverick-backend-watchdog.service`
- `scripts/deploy/systemd/maverick-backend-watchdog.timer`
- `scripts/deploy/nginx/maverick.example.conf`

Run the installer to bootstrap, verify, render, and optionally apply the deployment in one flow:

```bash
cd maverick
python3.12 scripts/install_maverick.py --hostname maverick.<host>.com --install-root .
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
- `.maverick/install/install-manifest.json`

The generated `.env.maverick` file is written outside `.maverick` by default and is loaded by the systemd units through `EnvironmentFile=`.
It contains local bootstrap credentials and secret refs and is written with mode `0600`.
The corresponding encrypted bootstrap secret envelopes and local secret-store key are written to the configured bootstrap paths. Keep all of those files out of version control and rotate generated values before any longer-lived public exposure.

The backend watchdog also loads `.env.maverick`, but rescue authority comes from the configured provider selection persisted in the control-plane store. A `MAVERICK_BACKEND_RESCUE_COMMAND` value is only a provider command override for the selected provider; it must not start rescue by itself when no provider is configured.

For a first-time HTTPS install, the installer initially writes an HTTP nginx config that can pass `nginx -t` without existing certificates and serve the ACME challenge.
After certbot obtains the certificate, the installer rewrites nginx with the final HTTPS config and reloads it.
The installer runs the local core health check before requesting TLS, so bind/port failures are reported even when Certbot is blocked by DNS, port `80`, or another active Certbot process.

Use `--render-only` to stop after rendering.

Use `--systemd-dir`, `--nginx-conf`, and `--install-env` to customize rendered output paths, and `--live-systemd-dir`, `--live-nginx-conf`, and `--live-nginx-enabled` to customize the live target paths used by apply.

Preflight checks are blocking for live apply. Missing systemd, nginx, certbot, Codex, bubblewrap, or frontend build tools fail the installer before live files are written when those tools are required by the selected mode. `--force` exists for reviewed operator exceptions only.

Post-apply health checks are also blocking. If any required health endpoint fails, the installer exits non-zero. Use `--skip-health-check` only when another supervisor is performing the same verification.

## Interactive Prompt Guide

For a public HTTPS deployment, most prompts should be accepted with Enter.
Only type `yes` or `y` at confirmation prompts that explicitly show `[y/N]` or `[Y/n]`.

Example command:

```bash
cd maverick
python3.12 scripts/install_maverick.py \
  --hostname maverick.<host>.com \
  --skip-bootstrap \
  --skip-verify \
  --install-root .
```

Prompt answers:

| Prompt | Correct response | Why |
| --- | --- | --- |
| `Install root [<checkout-root>]:` | Press Enter. | The install root must match the checkout root. |
| `Service user [ubuntu]:` | Press Enter. | The systemd unit should run as Linux user `ubuntu`; `yes` is not a valid service user unless that account exists. |
| `Service group [ubuntu]:` | Press Enter. | The systemd unit should run as Linux group `ubuntu`; `yes` is not a valid service group unless that group exists. |
| `Core bind host [127.0.0.1]:` | Press Enter. | The core should listen only locally; nginx exposes the public hostname. |
| `Core port [8014]:` | Press Enter. | This is the default internal core port. |
| `Rescue port [8015]:` | Press Enter. | This is the default internal rescue port. |
| `Public scheme [https] (https/http):` | Press Enter. | Public deployments should use HTTPS. |
| `Apply the rendered plan to the live system paths and manage services? [y/N]:` | Type `y` after reviewing the rendered plan. | This writes live systemd/nginx files and restarts services. |
| `Request a TLS certificate with certbot now? [y/N]:` | Type `y` only when DNS points to this machine and ports `80/443` are open. | Certbot must reach the hostname over the public internet. |

If a wrong value was entered at a prompt, press `Ctrl+C` and rerun the installer.
Do not continue with a wrong `Service user`, `Service group`, or `Install root`.

## Minimum Hardening

- bind the core service to `127.0.0.1`
- terminate TLS at nginx
- set upload limits
- keep logs outside the repository
- keep the configured control-plane store and `.env.maverick` on restricted filesystem permissions
- keep rescue automation disabled unless an operator has reviewed the policy
- restrict filesystem permissions on `.maverick/`, `data/control-plane/`, logs, and workspace roots

## Production Status

This is not a production deployment guide. It is a starting point for repeatable demo infrastructure.
