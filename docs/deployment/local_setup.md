# Local Setup

This guide describes the public clean-clone path for Maverick.

Maverick is experimental. Use fake data and local-only networking.

## Prerequisites

- Python 3.12, including the `venv` package
- Node.js 24 LTS (v24.11.0 or newer within the 24.x line) and npm
- `bubblewrap` on Linux for sandbox tests
- Codex CLI for Codex-backed runtime sessions
- `systemd`, nginx, and certbot for public service installs with TLS

The clean-clone local bootstrap uses the JSON control-plane adapter by default.
`.maverick` is rebuildable installation-local operating material, not the database. Deleting `.maverick` must not delete users, workspace membership, app bindings, provider/OAuth bindings, runtime token records, or secret values.

On Ubuntu, install Python 3.12 support and the sandbox dependency before running bootstrap:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv bubblewrap
```

Install Node.js 24 LTS through a system-wide package, runtime image, or version
manager that exposes `node` and `npm` to non-interactive Maverick processes such
as systemd services and agent sessions. Verify the selected runtime before using
`--build-frontends`:

```bash
node --version  # v24.11.0 or newer 24.x
npm --version
```

Maverick npm packages enforce this range with `engine-strict` for dependency
installs and runtime checks before direct Node-backed npm scripts.

For a public service install that should configure nginx and request HTTPS certificates, also install:

```bash
sudo apt-get install -y nginx certbot
```

Default JSON control-plane state is stored outside `.maverick`:

```bash
MAVERICK_CONTROL_STORE=json
MAVERICK_JSON_CONTROL_STORE_ROOT=data/control-plane/json
```

MongoDB can be selected during install or by environment:

```bash
MAVERICK_CONTROL_STORE=mongo \
MAVERICK_MONGODB_URI=mongodb://127.0.0.1:27017/maverick
```

For a local MongoDB service without authentication, leave `MongoDB username` empty during install. If MongoDB authentication is enabled, enter the username and real password in the installer prompts. The installer stores the password in the encrypted bootstrap secret store and writes only this ref to `.env.maverick`:

```bash
MAVERICK_MONGODB_USERNAME=maverick
MAVERICK_MONGODB_PASSWORD_REF=platform:secret-alias/mongodb-password
```

Do not put the MongoDB password in the MongoDB URI or in `.env.maverick`.

When the selected MongoDB URI points to the local machine and MongoDB is not reachable, the installer can start the local `mongod` service or install MongoDB Community with apt on supported Ubuntu/Debian hosts. For remote MongoDB URIs, the installer does not provision infrastructure and requires the configured server to already be reachable.

Secret values are encrypted by the core secret store. Hosted installs should load the secret-store key from a protected file:

```bash
MAVERICK_SECRET_KEY_FILE=<protected-secret-key-file>
MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT=data/bootstrap-secrets
```

`MAVERICK_SECRET_STORE_KEY` is only a development and compatibility fallback.
The bootstrap secret store is only for pre-adapter infrastructure secrets such as MongoDB passwords and platform signing secrets. It uses the same core secret envelope as the control-plane secret store and must stay outside `.maverick`.

The admin password is not a normal boot secret. Live installs require an initial admin password during the installer flow. The installer writes only its hash to the selected identity store and does not write `MAVERICK_ADMIN_PASSWORD` to `.env.maverick`.

After install, an operator can rotate or recover it later through the operator-only core CLI:

```bash
maverick core cli run core.identity.reset-admin-password --operator --username admin --password '<new-password>' --json
```

That command writes only the password hash to the durable identity store and revokes existing sessions for the admin user.

The installer also exposes the same choice:

```bash
python3.12 scripts/install_maverick.py --control-store json
python3.12 scripts/install_maverick.py --control-store mongo --mongodb-uri mongodb://127.0.0.1:27017/maverick
```

Adapter migrations run as one explicit operator workflow through core admin surfaces or the Settings UI: dry-run the target, write every control-plane collection to the target adapter, update the service environment file, and restart with only one adapter mounted. Backend startup must not silently migrate or delete control-plane state.

For the first public release, the recommended path is local CLI-first setup, not Docker and not a setup UI.

## Installer CLI

For a fresh install, use the installer CLI:

```bash
python3.12 scripts/install_maverick.py
```

The default flow is interactive. It:

- asks for the missing deployment values
- bootstraps the Python environment
- runs the core verification suite
- renders systemd units under `.maverick/install/systemd/`
- renders nginx config under `.maverick/install/nginx/`
- writes a service env file outside `.maverick`, defaulting to `.env.maverick`
- writes `.maverick/install/install-manifest.json`
- requires the initial admin password before live apply
- asks whether to apply the rendered plan to systemd and nginx, defaulting to yes
- runs final health checks
- asks whether to request a TLS certificate with `certbot` for public `https` installs, defaulting to yes

For public `https` installs, the installer applies systemd/nginx, checks the local core health endpoint, and then requests TLS. If Certbot is already running or DNS/port `80` is not ready, the installer exits non-zero with a TLS-specific message but leaves the applied services in place.
When `--skip-tls` is used with `--public-scheme https`, the installer assumes the certificate is managed externally or already exists, renders the HTTPS nginx server block directly, and lets `nginx -t` validate the referenced certificate files.

For a non-interactive public install with defaults accepted:

```bash
python3.12 scripts/install_maverick.py \
  --hostname maverick.<host>.com \
  --yes \
  --admin-password-file /path/to/admin-password.txt
```

For a local-only install without nginx or TLS:

```bash
python3.12 scripts/install_maverick.py --local-only
```

Use `--render-only` when you only want the generated files without changing the live system.

`--install-root` must currently match the checkout root. Clone the repository directly into the intended install directory and run the installer from that checkout.

Use `--install-root`, `--service-user`, `--service-group`, `--core-port`, `--rescue-port`, `--bind-host`, `--output-root`, `--systemd-dir`, `--nginx-conf`, `--install-env`, `--live-systemd-dir`, `--live-nginx-conf`, `--live-nginx-enabled`, and `--acme-root` to customize the flow.

For live apply, missing required preflight tools fail before the installer writes live system paths. `--force` is reserved for operator-reviewed exceptions. Failed post-apply health checks also return a non-zero exit code; `--skip-health-check` must be explicit.

## Human Install Walkthrough

Use this sequence on a new machine from the checkout root.

Clone the repository directly into the final install directory:

```bash
git clone https://github.com/PeterPsy/Maverick.git maverick
cd maverick
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
python3.12 scripts/install_maverick.py \
  --local-only \
  --render-only \
  --skip-bootstrap \
  --skip-verify \
  --install-root . \
  --yes
```

For a local-only systemd install:

```bash
python3.12 scripts/install_maverick.py \
  --local-only \
  --skip-bootstrap \
  --skip-verify \
  --install-root . \
  --yes
```

For a public hostname such as `maverick.<host>.com`, first make sure DNS points at the machine and ports `80` and `443` are reachable.
Then run:

```bash
python3.12 scripts/install_maverick.py \
  --hostname maverick.<host>.com \
  --skip-bootstrap \
  --skip-verify \
  --install-root .
```

When the installer prompts interactively, answer as follows:

| Prompt | Answer |
| --- | --- |
| `Install root [<checkout-root>]:` | Press Enter. The default must be the checkout root. |
| `Service user [ubuntu]:` | Press Enter, unless the Linux service user is different. Do not type `yes`. |
| `Service group [ubuntu]:` | Press Enter, unless the Linux service group is different. Do not type `yes`. |
| `Core bind host [127.0.0.1]:` | Press Enter. Nginx is the public entrypoint. |
| `Core port [8014]:` | Press Enter unless port `8014` is already used. |
| `Rescue port [8015]:` | Press Enter unless port `8015` is already used. |
| `Admin password:` | Enter the first admin password, then confirm it. The installer does not continue without it. |
| `Public scheme [https] (https/http):` | Press Enter for HTTPS. |
| `Apply the rendered plan... [Y/n]:` | Press Enter to install live systemd/nginx paths and start services. Type `n` for render-only behavior. |
| `Request a TLS certificate with certbot now? [Y/n]:` | Press Enter only when DNS and ports `80/443` are ready. Type `n` to skip TLS for now. |

After live apply, verify:

```bash
systemctl status --no-pager maverick-core.service
systemctl status --no-pager maverick-rescue.service
curl http://127.0.0.1:8014/health
```

For a public HTTPS install, also verify:

```bash
curl https://maverick.<host>.com/health
```

The generated bootstrap credential refs are in:

```bash
.env.maverick
```

The corresponding encrypted bootstrap secret envelopes and local secret-store key are under the configured `MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT` and `MAVERICK_SECRET_KEY_FILE` paths.

## Python Environment

```bash
./scripts/bootstrap_local.sh
source .venv/bin/activate
```

Bootstrap does not rewrite existing local JSON path fields by default.
When moving a checkout and intentionally rebasing local JSON path fields, run:

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
`scripts/bootstrap_local.sh` creates a local `.env` when one does not already exist. The generated file includes the admin username and bootstrap secret refs, but not an admin password.
The installer/systemd profile defaults to core port `8014` and rescue port `8015` to avoid clashing with a developer server.
Use `--core-port` or `MAVERICK_PORT` when you need a different profile.

## Frontend Apps

Apps with source are built from their app directories:

```bash
cd apps/chat
npm ci
npm run build
```

Frontend apps must have a real build script that regenerates their declared `frontend/dist` artifact; see `docs/development/generated_artifacts.md`.

To build every app frontend during bootstrap:

```bash
MAVERICK_BUILD_FRONTENDS=1 ./scripts/bootstrap_local.sh
```

The installer exposes the same path:

```bash
python3.12 scripts/install_maverick.py --local-only --build-frontends
```

## Environment Variables

Copy `.env.example` only as a local starting point. Do not commit `.env`.
`scripts/run_local.sh` loads `.env` automatically when present, otherwise it falls back to `.env.maverick`.
Systemd installs use the generated `.env.maverick` file by default.

Do not put production OAuth credentials or API keys into raw environment variables. Store them through the core secret domain and expose them to apps/providers only through secret refs and bindings.

## CLI Discovery

Use the checked-in wrapper for machine-readable discovery:

```bash
./scripts/maverick apps list --json
./scripts/maverick core cli list --json
./scripts/maverick core mcp list --json
./scripts/maverick core cli run developer-context.list --json
```

## Persistence

Bootstrap and runtime create the installation-local directory layout for workspace-owned data. Runtime, app data, and local bootstrap state must not be committed.

Use fake local data until the production persistence and secret-storage hardening work is complete.
