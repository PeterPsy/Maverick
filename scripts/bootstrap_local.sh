#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BUILD_FRONTENDS="${MAVERICK_BUILD_FRONTENDS:-0}"
REBASE_LOCAL_STATE="${MAVERICK_REBASE_LOCAL_STATE_PATHS:-0}"

for argument in "$@"; do
  case "${argument}" in
    --build-frontends)
      BUILD_FRONTENDS=1
      ;;
    --rebase-local-state)
      REBASE_LOCAL_STATE=1
      ;;
  esac
done

if [[ "${REBASE_LOCAL_STATE}" == "1" ]]; then
  python3 "${ROOT_DIR}/scripts/rebase_local_state_paths.py" >/dev/null
fi

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"

if [[ "${BUILD_FRONTENDS}" == "1" ]]; then
  python3 "${ROOT_DIR}/scripts/build_app_frontends.py"
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
