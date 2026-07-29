#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python -m ruff check .
bash scripts/check_types.sh

if [[ "${MARDAS_ALLOW_PYTEST_PLUGINS:-0}" != "1" ]]; then
  export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
fi

if [[ "${MARDAS_RENDER_SMOKE:-0}" == "1" ]]; then
  python scripts/render_smoke.py
  MARDAS_RENDER_SMOKE=0 python -m pytest "$@"
else
  python -m pytest "$@"
fi
