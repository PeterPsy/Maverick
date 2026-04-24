# Local Setup

This guide describes the public clean-clone path for Maverick v3.

Maverick is experimental. Use fake data and local-only networking.

## Prerequisites

- Python 3.12
- Node.js and npm
- `bubblewrap` on Linux for sandbox tests
- Codex CLI for Codex-backed runtime sessions

The current clean-clone local bootstrap uses JSON files under `.maverick/local-state`.
MongoDB remains a future/hosted persistence adapter target and is not required for the current local installer path.

For the first public release, the recommended path is local CLI-first setup, not Docker and not a setup UI.

## Installer CLI

For a fresh install, use the installer CLI:

```bash
python3 scripts/install_maverick.py
```

The default flow is interactive. It:

- asks for the missing deployment values
- bootstraps the Python environment
- runs the core verification suite
- renders systemd units under `.maverick/install/systemd/`
- renders nginx config under `.maverick/install/nginx/`
- writes a service env file under `.maverick/install/maverick3.env`
- writes `.maverick/install/install-manifest.json`
- offers to apply the rendered plan to systemd and nginx
- offers to request a TLS certificate with `certbot` for public `https` installs
- runs final health checks

For a non-interactive public install with defaults accepted:

```bash
python3 scripts/install_maverick.py --hostname maverick.<host>.com --yes
```

For a local-only install without nginx or TLS:

```bash
python3 scripts/install_maverick.py --local-only
```

Use `--render-only` when you only want the generated files without changing the live system.

`--install-root` must currently match the checkout root. To install under `/opt/maverick-v3`, clone the repository there and run the installer from that checkout.

Use `--install-root`, `--service-user`, `--service-group`, `--core-port`, `--rescue-port`, `--bind-host`, `--output-root`, `--systemd-dir`, `--nginx-conf`, `--install-env`, `--live-systemd-dir`, `--live-nginx-conf`, `--live-nginx-enabled`, and `--acme-root` to customize the flow.

For live apply, missing required preflight tools fail before the installer writes live system paths. `--force` is reserved for operator-reviewed exceptions. Failed post-apply health checks also return a non-zero exit code; `--skip-health-check` must be explicit.

## Human Install Walkthrough

Use this sequence on a new machine when installing under `/home/ubuntu/projects/maverick-v3`.

Clone the repository directly into the final install directory:

```bash
mkdir -p /home/ubuntu/projects
cd /home/ubuntu/projects
git clone https://github.com/PieroVersy/Maverick.git maverick-v3
cd /home/ubuntu/projects/maverick-v3
git checkout main
```

Bootstrap and verify:

```bash
./scripts/bootstrap_local.sh
source .venv/bin/activate
./scripts/verify_local.sh
```

The verification suite intentionally prints traceback logs for tests that simulate app crashes.
Treat the run as successful only when the final summary says `OK`.

Render first without touching live systemd or nginx:

```bash
python3 scripts/install_maverick.py \
  --local-only \
  --render-only \
  --skip-bootstrap \
  --skip-verify \
  --install-root /home/ubuntu/projects/maverick-v3 \
  --yes
```

For a local-only systemd install:

```bash
python3 scripts/install_maverick.py \
  --local-only \
  --skip-bootstrap \
  --skip-verify \
  --install-root /home/ubuntu/projects/maverick-v3 \
  --yes
```

For a public hostname such as `maverick.<host>.com`, first make sure DNS points at the machine and ports `80` and `443` are reachable.
Then run:

```bash
python3 scripts/install_maverick.py \
  --hostname maverick.<host>.com \
  --skip-bootstrap \
  --skip-verify \
  --install-root /home/ubuntu/projects/maverick-v3
```

When the installer prompts interactively, answer as follows:

| Prompt | Answer |
| --- | --- |
| `Install root [/home/ubuntu/projects/maverick-v3]:` | Press Enter. The default must be the checkout root. |
| `Service user [ubuntu]:` | Press Enter, unless the Linux service user is different. Do not type `yes`. |
| `Service group [ubuntu]:` | Press Enter, unless the Linux service group is different. Do not type `yes`. |
| `Core bind host [127.0.0.1]:` | Press Enter. Nginx is the public entrypoint. |
| `Core port [8014]:` | Press Enter unless port `8014` is already used. |
| `Rescue port [8015]:` | Press Enter unless port `8015` is already used. |
| `Public scheme [https] (https/http):` | Press Enter for HTTPS. |
| `Apply the rendered plan... [y/N]:` | Type `y` only after reviewing the plan. |
| `Request a TLS certificate with certbot now? [y/N]:` | Type `y` only when DNS and ports `80/443` are ready. |

After live apply, verify:

```bash
systemctl status --no-pager maverick3-core.service
systemctl status --no-pager maverick3-rescue.service
curl http://127.0.0.1:8014/health
```

For a public HTTPS install, also verify:

```bash
curl https://maverick.<host>.com/health
```

The generated bootstrap credentials and signing secrets are in:

```bash
.maverick/install/maverick3.env
```

## Python Environment

```bash
./scripts/bootstrap_local.sh
source .venv/bin/activate
```

Bootstrap does not rewrite existing local-state paths by default.
When moving a checkout and intentionally migrating local JSON state, run:

```bash
./scripts/bootstrap_local.sh --rebase-local-state
```

## Verify Core

```bash
./scripts/verify_local.sh
```

## Run Core Host

```bash
./scripts/run_local.sh
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

`scripts/run_local.sh` is the development profile and defaults to port `8000`.
The installer/systemd profile defaults to core port `8014` and rescue port `8015` to avoid clashing with a developer server.
Use `--core-port` or `MAVERICK_PORT` when you need a different profile.

## Frontend Apps

Apps with source are built from their app directories:

```bash
cd apps/chat
npm ci
npm run build
```

Apps with `lifecycle.rebuild: true` must have a real build script.
Apps with only committed `frontend/dist` artifacts must declare `lifecycle.rebuild: false`; see `docs/development/generated_artifacts.md`.

To build every app frontend during bootstrap:

```bash
MAVERICK_BUILD_FRONTENDS=1 ./scripts/bootstrap_local.sh
```

The installer exposes the same path:

```bash
python3 scripts/install_maverick.py --local-only --build-frontends
```

## Environment Variables

Copy `.env.example` only as a local starting point. Do not commit `.env`.
`scripts/run_local.sh` loads `.env` automatically when present.
Systemd installs use the generated `.maverick/install/maverick3.env` file instead.

Production-quality secret storage is not implemented yet. Do not put production OAuth credentials or API keys into the local bootstrap environment.

## CLI Discovery

Use the checked-in wrapper for machine-readable discovery:

```bash
./scripts/maverick apps list --json
./scripts/maverick core cli list --json
./scripts/maverick core mcp list --json
./scripts/maverick core cli run developer-context.list --json
```

## Persistence

The repository contains the directory layout for workspace-owned data. Runtime, app data, and local bootstrap state must not be committed.

Use fake local data until the production persistence and secret-storage hardening work is complete.
