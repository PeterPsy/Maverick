#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
HOST="${LOOPINO_HOST:-127.0.0.1}"
PORT="${LOOPINO_PORT:-8000}"
PYTHON_BIN="${LOOPINO_PYTHON:-}"

if [[ -d "${VENV_DIR}" ]]; then
  source "${VENV_DIR}/bin/activate"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.12)"
  else
    PYTHON_BIN="python3"
  fi
fi

ENV_FILE=""
if [[ -f "${ROOT_DIR}/.env" ]]; then
  ENV_FILE="${ROOT_DIR}/.env"
elif [[ -f "${ROOT_DIR}/.env.loopino" ]]; then
  ENV_FILE="${ROOT_DIR}/.env.loopino"
fi

if [[ -z "${ENV_FILE}" ]]; then
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/install_loopino.py" \
    --local-only \
    --skip-bootstrap \
    --skip-verify \
    --render-only \
    --yes \
    --install-env "${ROOT_DIR}/.env" \
    --core-port "${PORT}" \
    >/dev/null
  ENV_FILE="${ROOT_DIR}/.env"
fi

if [[ -n "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ENV_FILE}"
  set +a
  HOST="${LOOPINO_HOST:-${HOST}}"
  PORT="${LOOPINO_PORT:-${PORT}}"
fi

if [[ -z "${LOOPINO_ADMIN_USERNAME:-}" ]]; then
  cat >&2 <<EOF
LOOPINO_ADMIN_USERNAME is required.

Run bootstrap to generate a local environment file:
  ./scripts/bootstrap_local.sh

Or create .env from .env.example and set LOOPINO_ADMIN_USERNAME.
EOF
  exit 1
fi

cd "${ROOT_DIR}"
exec uvicorn core.api.asgi_application:app --host "${HOST}" --port "${PORT}"
