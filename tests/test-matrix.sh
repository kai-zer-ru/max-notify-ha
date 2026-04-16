#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../" && pwd)"
echo "ROOT_DIR: ${ROOT_DIR}"

run_for_env() {
  local env_dir="$1"
  local label="$2"
  local python_bin="${ROOT_DIR}/${env_dir}/bin/python"

  if [[ ! -x "${python_bin}" ]]; then
    echo "ERROR: ${label} -> не найден интерпретатор: ${python_bin}" >&2
    exit 1
  fi

  echo
  echo "=== ${label} (${env_dir}) ==="
  "${python_bin}" -m pytest -q
}

run_for_env ".venv-ha-2026.02" "Home Assistant 2026.02"
run_for_env ".venv-ha-2026.03" "Home Assistant 2026.03"
run_for_env ".venv-ha-2026.04" "Home Assistant 2026.04"

echo
echo "OK: все окружения прошли тесты."
