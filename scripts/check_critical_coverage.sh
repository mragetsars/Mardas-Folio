#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
critical_modules=(
  quality pdf_navigation protocol runtime application sidecar workspace
  document_store document_assets render_requests request_validation engine_errors file_io
  render_contracts page_geometry print_layout projects publishing
)
critical_sources=()
for module in "${critical_modules[@]}"; do
  critical_sources+=("mardas_folio.$module")
done
source_list=$(IFS=,; printf '%s' "${critical_sources[*]}")

coverage erase
coverage run \
  --branch \
  --source="$source_list" \
  -m pytest -q \
  tests/engine/test_renderer_options.py \
  tests/engine/test_pdf_toc_destinations.py \
  tests/engine/test_application_api.py \
  tests/engine/test_sidecar_protocol.py \
  tests/engine/test_document_save_consistency.py \
  tests/engine/test_document_encoding_roundtrip.py \
  tests/engine/test_asset_boundary.py \
  tests/engine/test_file_transactions.py \
  tests/engine/test_file_io.py \
  tests/engine/test_engine_boundaries.py \
  tests/engine/test_book_workspace_lifecycle.py \
  tests/engine/test_markdown_links.py \
  tests/engine/test_page_preview_payload.py \
  tests/engine/test_studio_project_workspace.py \
  tests/engine/test_workspace_discovery.py
coverage report --show-missing --fail-under="${MARDAS_CRITICAL_COVERAGE_MIN:-60}"
coverage xml -o build/coverage/critical-coverage.xml
