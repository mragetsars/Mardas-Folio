#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
coverage erase
coverage run \
  --branch \
  --source=mardas_folio.quality,mardas_folio.pdf_navigation,mardas_folio.protocol,mardas_folio.runtime,mardas_folio.application,mardas_folio.sidecar \
  -m pytest -q \
  tests/test_renderer_options.py \
  tests/test_pdf_toc_destinations.py \
  tests/test_application_api.py \
  tests/test_sidecar_protocol.py
coverage report --show-missing --fail-under="${MARDAS_CRITICAL_COVERAGE_MIN:-60}"
coverage xml -o build/coverage/critical-coverage.xml
