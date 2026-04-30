#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BUILD_FRONTENDS="${MAVERICK_BUILD_FRONTENDS:-0}"
REBASE_LOCAL_STATE="${MAVERICK_REBASE_LOCAL_STATE_PATHS:-0}"
PYTHON_BIN="${MAVERICK_PYTHON:-}"
PYPROJECT_EXTRAS="${MAVERICK_PYPROJECT_EXTRAS:-dev}"

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

detect_python() {
  if [[ -n "${PYTHON_BIN}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
    return
  fi
  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  printf 'python3\n'
}

PYTHON_BIN="$(detect_python)"

if ! "${PYTHON_BIN}" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
then
  cat >&2 <<EOF
Maverick requires Python 3.12 or newer.

The selected interpreter is:
  ${PYTHON_BIN}

Install Python 3.12 and its venv package, then rerun bootstrap. On Ubuntu:
  sudo apt-get update
  sudo apt-get install -y python3.12 python3.12-venv

If Python 3.12 is installed in a custom path, run:
  MAVERICK_PYTHON=/path/to/python3.12 ./scripts/bootstrap_local.sh
EOF
  exit 1
fi

if [[ "${REBASE_LOCAL_STATE}" == "1" ]]; then
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/rebase_local_state_paths.py" >/dev/null
fi

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[${PYPROJECT_EXTRAS}]"

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  python3 "${ROOT_DIR}/scripts/install_maverick.py" \
    --local-only \
    --skip-bootstrap \
    --skip-verify \
    --render-only \
    --yes \
    --install-env "${ROOT_DIR}/.env" \
    --core-port "${MAVERICK_PORT:-8000}" \
    >/dev/null
fi

if [[ "${BUILD_FRONTENDS}" == "1" ]]; then
  python3 "${ROOT_DIR}/scripts/build_app_frontends.py"
fi

cat <<EOF
Bootstrap complete.

Local environment file:
  .env

Activate the virtual environment:
  source .venv/bin/activate

Run core checks:
  ./scripts/verify_local.sh

Run the local host:
  ./scripts/run_local.sh
EOF
