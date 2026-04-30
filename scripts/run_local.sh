#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
HOST="${MAVERICK_HOST:-127.0.0.1}"
PORT="${MAVERICK_PORT:-8000}"

ENV_FILE=""
if [[ -f "${ROOT_DIR}/.env" ]]; then
  ENV_FILE="${ROOT_DIR}/.env"
elif [[ -f "${ROOT_DIR}/.env.maverick" ]]; then
  ENV_FILE="${ROOT_DIR}/.env.maverick"
fi

if [[ -n "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ENV_FILE}"
  set +a
  HOST="${MAVERICK_HOST:-${HOST}}"
  PORT="${MAVERICK_PORT:-${PORT}}"
fi

if [[ -d "${VENV_DIR}" ]]; then
  source "${VENV_DIR}/bin/activate"
fi

cd "${ROOT_DIR}"
exec uvicorn core.api.asgi_application:app --host "${HOST}" --port "${PORT}"
