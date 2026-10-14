#!/usr/bin/env bash
# Source this in noninteractive build/test processes; never reads operator auth.
LOOPINO_INSTALL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${LOOPINO_INSTALL_ROOT}/.venv/bin:${LOOPINO_INSTALL_ROOT}/.toolchains/bin:${LOOPINO_INSTALL_ROOT}/.toolchains/node/bin:${PATH}"
export LD_LIBRARY_PATH="${LOOPINO_INSTALL_ROOT}/.toolchains/sqlite/3.51.3/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export TMPDIR="${LOOPINO_INSTALL_ROOT}/.cache/tmp"
export PIP_CACHE_DIR="${LOOPINO_INSTALL_ROOT}/.cache/pip"
export npm_config_cache="${LOOPINO_INSTALL_ROOT}/.cache/npm"
export XDG_CACHE_HOME="${LOOPINO_INSTALL_ROOT}/.cache"
export NODE_OPTIONS="--max-old-space-size=1536"
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
mkdir -p "${TMPDIR}" "${PIP_CACHE_DIR}" "${npm_config_cache}"
