#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -z "${SOURCE_DATE_EPOCH:-}" ]]; then
  SOURCE_DATE_EPOCH="$(git log -1 --format=%ct 2>/dev/null || printf '946684800')"
fi
export SOURCE_DATE_EPOCH
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export TZ="${TZ:-UTC}"
umask 022

rm -rf dist

build_frontend_available() {
  (
    cd "${TMPDIR:-/tmp}"
    python - <<'PY'
from importlib.util import find_spec

try:
    available = find_spec("build.__main__") is not None
except ModuleNotFoundError:
    available = False
raise SystemExit(0 if available else 1)
PY
  )
}

build_with_current_setuptools_backend() {
  echo "[build_dist] PyPA build frontend is unavailable; using setuptools.build_meta without isolation." >&2
  MARDAS_REPO_ROOT="$repo_root" python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

from setuptools import build_meta

repo_root = Path(os.environ["MARDAS_REPO_ROOT"]).resolve()
dist_dir = repo_root / "dist"
dist_dir.mkdir(parents=True, exist_ok=True)
os.chdir(repo_root)

build_meta.build_sdist(str(dist_dir))
build_meta.build_wheel(str(dist_dir))
PY
}

if build_frontend_available; then
  if [[ "${MARDAS_BUILD_NO_ISOLATION:-0}" == "1" ]]; then
    python -m build --no-isolation --skip-dependency-check
  else
    python -m build
  fi
elif [[ "${MARDAS_BUILD_NO_ISOLATION:-0}" == "1" ]]; then
  build_with_current_setuptools_backend
else
  cat >&2 <<'EOF_ERROR'
[build_dist] ERROR: the PyPA 'build' frontend is not installed.
Install the development dependencies with:
  python -m pip install -e '.[dev]'
For an offline/pre-provisioned environment, use:
  MARDAS_BUILD_NO_ISOLATION=1 bash scripts/build_dist.sh
EOF_ERROR
  exit 2
fi

for archive in dist/*.tar.gz; do
  [[ -e "$archive" ]] || continue
  python scripts/normalize_sdist.py "$archive" --epoch "$SOURCE_DATE_EPOCH"
done
