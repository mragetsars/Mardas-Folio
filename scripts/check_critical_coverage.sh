#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
critical_modules=(
  quality pdf_navigation protocol runtime application sidecar workspace
  document_store document_assets render_requests request_validation engine_errors file_io
  render_contracts page_geometry print_layout
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
  tests/test_renderer_options.py \
  tests/test_pdf_toc_destinations.py \
  tests/test_application_api.py \
  tests/test_sidecar_protocol.py \
  tests/test_document_save_consistency.py \
  tests/test_document_encoding_roundtrip.py \
  tests/test_asset_boundary.py \
  tests/test_file_transactions.py \
  tests/test_file_io.py \
  tests/test_engine_boundaries.py \
  tests/test_book_workspace_lifecycle.py \
  tests/test_markdown_links.py \
  tests/test_page_preview_payload.py \
  tests/test_studio_project_workspace.py \
  tests/test_workspace_discovery.py
coverage report --show-missing --fail-under="${MARDAS_CRITICAL_COVERAGE_MIN:-60}"
coverage xml -o build/coverage/critical-coverage.xml
