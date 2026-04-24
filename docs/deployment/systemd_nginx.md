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
python3 scripts/install_maverick.py --hostname maverick.<host>.com --install-root /opt/maverick-v3
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

For a first-time HTTPS install, the installer initially writes an HTTP nginx config that can pass `nginx -t` without existing certificates and serve the ACME challenge.
After certbot obtains the certificate, the installer rewrites nginx with the final HTTPS config and reloads it.

Use `--render-only` to stop after rendering.

Use `--systemd-dir`, `--nginx-conf`, and `--install-env` to customize rendered output paths, and `--live-systemd-dir`, `--live-nginx-conf`, and `--live-nginx-enabled` to customize the live target paths used by apply.

Preflight checks are blocking for live apply. Missing systemd, nginx, certbot, Codex, bubblewrap, or frontend build tools fail the installer before live files are written when those tools are required by the selected mode. `--force` exists for reviewed operator exceptions only.

Post-apply health checks are also blocking. If any required health endpoint fails, the installer exits non-zero. Use `--skip-health-check` only when another supervisor is performing the same verification.

## Interactive Prompt Guide

For a public HTTPS deployment, most prompts should be accepted with Enter.
Only type `yes` or `y` at confirmation prompts that explicitly show `[y/N]` or `[Y/n]`.

Example command:

```bash
cd /home/ubuntu/projects/maverick-v3
python3 scripts/install_maverick.py \
  --hostname maverick.<host>.com \
  --skip-bootstrap \
  --skip-verify \
  --install-root /home/ubuntu/projects/maverick-v3
```

Prompt answers:

| Prompt | Correct response | Why |
| --- | --- | --- |
| `Install root [/home/ubuntu/projects/maverick-v3]:` | Press Enter. | The install root must match the checkout root. |
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
- do not store production secrets in local JSON state
- keep rescue automation disabled unless an operator has reviewed the policy
- restrict filesystem permissions on `.maverick/`, logs, and workspace roots

## Production Status

This is not a production deployment guide. It is a starting point for repeatable demo infrastructure.
