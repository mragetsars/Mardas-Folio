#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
coverage erase
coverage run \
  --branch \
  --source=mardas_md2pdf.quality,mardas_md2pdf.pdf_navigation \
  -m pytest -q \
  tests/test_renderer_options.py \
  tests/test_pdf_toc_destinations.py
coverage report --show-missing --fail-under="${MARDAS_CRITICAL_COVERAGE_MIN:-60}"
coverage xml -o build/coverage/critical-coverage.xml
