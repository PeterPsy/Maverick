#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ -d "${VENV_DIR}" ]]; then
  source "${VENV_DIR}/bin/activate"
fi

cd "${ROOT_DIR}"
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall core tests scripts
python3 scripts/check_unused_imports.py
