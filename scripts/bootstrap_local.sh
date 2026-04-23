#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BUILD_FRONTENDS="${MAVERICK_BUILD_FRONTENDS:-0}"

if [[ "${1:-}" == "--build-frontends" ]]; then
  BUILD_FRONTENDS=1
fi

python3 "${ROOT_DIR}/scripts/rebase_local_state_paths.py" >/dev/null

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

if [[ "${BUILD_FRONTENDS}" == "1" ]]; then
  while IFS= read -r manifest; do
    app_dir="$(dirname "${manifest}")"
    echo "==> Building frontend dependencies in ${app_dir}"
    (cd "${app_dir}" && npm ci && npm run build)
  done < <(find "${ROOT_DIR}/apps" -mindepth 2 -maxdepth 2 -name package-lock.json | sort)
fi

cat <<EOF
Bootstrap complete.

Activate the virtual environment:
  source .venv/bin/activate

Run core checks:
  ./scripts/verify_local.sh

Run the local host:
  ./scripts/run_local.sh
EOF
