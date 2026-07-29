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

run_visual_qa="${MARDAS_RELEASE_VISUAL_QA:-0}"
preflight_pages="${MARDAS_PREFLIGHT_PAGES:-1,2,3}"
preflight_timeout="${MARDAS_PREFLIGHT_TIMEOUT:-60}"

bash scripts/check.sh
bash scripts/check_critical_coverage.sh
if [[ "${MARDAS_SKIP_SECURITY_AUDIT:-0}" != "1" ]]; then
  bash scripts/security_audit.sh
fi

tmp_pdf="${TMPDIR:-/tmp}/mardas-md2pdf-release-smoke.pdf"
timeout "${MARDAS_RELEASE_SMOKE_TIMEOUT:-240}" \
  python -m mardas_md2pdf.cli \
    docs/guides/GUIDE.en.md \
    -o "$tmp_pdf" \
    --toc \
    --style github \
    --palette blue \
    --mode light \
    --timeout-ms "${MARDAS_TIMEOUT_MS:-180000}" \
    --progress off
test -s "$tmp_pdf"

bash scripts/build_examples.sh
python scripts/check_pdf_preflight.py \
  examples/GUIDE.en.pdf \
  examples/GUIDE.fa.pdf \
  --pages "$preflight_pages" \
  --timeout "$preflight_timeout" \
  --output build/release/pdf-preflight.json

if [[ "$run_visual_qa" == "1" ]]; then
  python scripts/run_visual_qa_matrix.py \
    --output-dir build/release/visual-qa \
    --render-png \
    --raster-timeout "${MARDAS_RASTER_TIMEOUT:-60}" \
    --chunk-timeout "${MARDAS_CHUNK_TIMEOUT:-900}" \
    --resume \
    --clean
else
  python scripts/run_visual_qa_matrix.py \
    --output-dir build/release/visual-qa-smoke \
    --max-cases "${MARDAS_RELEASE_VISUAL_QA_CASES:-1}" \
    --render-png \
    --raster-timeout "${MARDAS_RASTER_TIMEOUT:-60}" \
    --chunk-timeout "${MARDAS_CHUNK_TIMEOUT:-180}" \
    --fail-fast \
    --clean
fi

visual_root="build/release/visual-qa"
if [[ "$run_visual_qa" != "1" ]]; then
  visual_root="build/release/visual-qa-smoke"
fi
contract_index=0
for manifest in "$visual_root"/appearance/chunk-*/manifest.json; do
  [[ -e "$manifest" ]] || continue
  contract_index=$((contract_index + 1))
  python scripts/check_visual_contracts.py \
    --appearance-manifest "$manifest" \
    --output-dir "build/release/visual-contracts/appearance-$contract_index"
done
contract_index=0
for manifest in "$visual_root"/features/chunk-*/manifest.json; do
  [[ -e "$manifest" ]] || continue
  contract_index=$((contract_index + 1))
  python scripts/check_visual_contracts.py \
    --features-manifest "$manifest" \
    --output-dir "build/release/visual-contracts/features-$contract_index"
done

bash scripts/build_dist.sh

wheel_path="$(find dist -maxdepth 1 -type f -name '*.whl' -print -quit)"
if [[ -z "$wheel_path" ]]; then
  echo "Release gate failed: wheel artifact was not produced." >&2
  exit 1
fi

verify_venv="$(mktemp -d "${TMPDIR:-/tmp}/mardas-md2pdf-release-venv.XXXXXX")"
project_smoke="$(mktemp -d "${TMPDIR:-/tmp}/mardas-md2pdf-project-smoke.XXXXXX")"
cleanup_release_gate() {
  rm -rf "$verify_venv" "$project_smoke" "$tmp_pdf"
}
trap cleanup_release_gate EXIT

python -m venv "$verify_venv"
venv_python="$verify_venv/bin/python"
venv_bin="$verify_venv/bin"
if [[ "${OS:-}" == "Windows_NT" ]]; then
  venv_python="$verify_venv/Scripts/python.exe"
  venv_bin="$verify_venv/Scripts"
fi

"$venv_python" -m pip install --disable-pip-version-check "$wheel_path"
"$venv_python" -m pip check
"$venv_bin/mrs-md2pdf" --version
"$venv_bin/mrs-md2pdf" --help >/dev/null
"$venv_bin/mrs-md2pdf" --list-styles >/dev/null
"$venv_bin/mrs-md2pdf-sidecar" --version
"$venv_bin/mrs-md2pdf-sidecar" --health > "$project_smoke/sidecar-health.json"
"$venv_python" - "$project_smoke/sidecar-health.json" <<'PY_SIDECAR_HEALTH'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "ok":
    raise SystemExit("Installed-wheel sidecar health status is not ok")
if payload.get("protocol") != "mardas-sidecar" or payload.get("protocol_version") != 1:
    raise SystemExit("Installed-wheel sidecar protocol identity is invalid")
if not payload.get("engine_api_version"):
    raise SystemExit("Installed-wheel sidecar did not expose an engine API version")
PY_SIDECAR_HEALTH
"$venv_bin/mrs-md2pdf" init "$project_smoke" --book
"$venv_python" - "$project_smoke" <<'PY_REFERENCE_PROJECT'
import sys
from pathlib import Path

root = Path(sys.argv[1])
config = root / "mardas.toml"
text = config.read_text(encoding="utf-8")
text = text.replace('# language = "fa-IR"', 'language = "en-US"', 1)
text = text.replace(
    '[bibliography]\nenabled = false',
    '[bibliography]\nenabled = true',
    1,
)
text = text.replace(
    '# sources = ["references.bib"]',
    'sources = ["references.bib"]',
    1,
)
text = text.replace(
    '[references]\nenabled = false',
    '[references]\nenabled = true',
    1,
)
text = text.replace('numbering_scope = "global"', 'numbering_scope = "chapter"', 1)
text = text.replace("list_of_figures = false", "list_of_figures = true", 1)
text = text.replace("list_of_tables = false", "list_of_tables = true", 1)
text = text.replace("list_of_equations = false", "list_of_equations = true", 1)
text = text.replace("list_of_listings = false", "list_of_listings = true", 1)
config.write_text(text, encoding="utf-8", newline="\n")
(root / "assets").mkdir(exist_ok=True)
(root / "assets" / "model.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120">'
    '<rect width="320" height="120" rx="12" fill="#dbeafe"/>'
    '<text x="160" y="68" text-anchor="middle" font-family="sans-serif">Model</text>'
    '</svg>',
    encoding="utf-8",
)
(root / "references.bib").write_text(
    "@article{doe2024, author={Doe, Jane}, title={Release Evidence}, year={2024}}\n"
    "@book{smith2022, author={Smith, Alex}, title={Release Methods}, year={2022}}\n",
    encoding="utf-8",
)
chapter_one = (
    "# Introduction\n\n"
    "See @fig:model, @tbl:metrics, @eq:energy, and @lst:loop. "
    "Prior evidence is documented in [@doe2024].\n\n"
    "![Model](../assets/model.svg)\n\n"
    "Figure: Release model {#fig:model}\n\n"
    "| Metric | Value |\n|---|---:|\n| Pass | 1 |\n\n"
    "Table: Release metrics {#tbl:metrics}\n\n"
    "$$\nE = mc^2\n$$\n\n{#eq:energy}\n"
)
chapter_two = (
    "# Main Content\n\n"
    "The release method follows @smith2022.\n\n"
    "```python title=\"Release loop\" {#lst:loop}\n"
    "print(\"release\")\n"
    "```\n"
)
(root / "chapters" / "01-introduction.md").write_text(chapter_one, encoding="utf-8")
(root / "chapters" / "02-content.md").write_text(chapter_two, encoding="utf-8")
PY_REFERENCE_PROJECT
printf '%s\n' '# Project command smoke' > "$project_smoke/report.md"
"$venv_bin/mrs-md2pdf" validate "$project_smoke/report.md" --format json > "$project_smoke/validate.json"
"$venv_bin/mrs-md2pdf" explain-config "$project_smoke/report.md" --format json > "$project_smoke/explain.json"
"$venv_bin/mrs-md2pdf" doctor "$project_smoke/report.md" --format json > "$project_smoke/doctor.json"
"$venv_bin/mrs-md2pdf" validate-book "$project_smoke" --format json > "$project_smoke/validate-book.json"
"$venv_bin/mrs-md2pdf" explain-book "$project_smoke" --format json > "$project_smoke/explain-book.json"
"$venv_bin/mrs-md2pdf" build-book "$project_smoke" --format json --progress off > "$project_smoke/build-book.json"
test -s "$project_smoke/dist/book.pdf"
"$venv_bin/mrs-md2pdf" audit-accessibility "$project_smoke/report.md" --format json > "$project_smoke/audit-accessibility.json"
"$venv_bin/mrs-md2pdf" audit-book-accessibility "$project_smoke" --format json > "$project_smoke/audit-book-accessibility.json"
"$venv_bin/mrs-md2pdf" audit-pdf "$project_smoke/dist/book.pdf" --format json --fail-on never > "$project_smoke/audit-pdf.json"
"$venv_python" - "$project_smoke" <<'PY_PROJECT'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for name in (
    "validate",
    "explain",
    "doctor",
    "validate-book",
    "explain-book",
    "build-book",
    "audit-accessibility",
    "audit-book-accessibility",
    "audit-pdf",
):
    payload = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    if not payload.get("ok"):
        raise SystemExit(f"Project command smoke failed: {name}")
book = json.loads((root / "build-book.json").read_text(encoding="utf-8"))
if book.get("chapter_count") != 2:
    raise SystemExit("Book Mode smoke did not preserve the starter chapter manifest")
if not str(book.get("output", "")).endswith("dist/book.pdf"):
    raise SystemExit("Book Mode smoke wrote an unexpected output path")
if book.get("numbered_objects") != 4:
    raise SystemExit("Cross-reference smoke did not number all four object kinds")
if book.get("cited_entries") != 2:
    raise SystemExit("Citation smoke did not resolve both cited keys")
if book.get("bibliography_entries") != 2:
    raise SystemExit("Citation smoke did not generate both bibliography entries")
source_audit = json.loads((root / "audit-accessibility.json").read_text(encoding="utf-8"))
book_audit = json.loads((root / "audit-book-accessibility.json").read_text(encoding="utf-8"))
pdf_audit = json.loads((root / "audit-pdf.json").read_text(encoding="utf-8"))
if source_audit.get("summary", {}).get("error") != 0:
    raise SystemExit("Installed-wheel source accessibility audit reported an error")
if book_audit.get("summary", {}).get("error") != 0:
    raise SystemExit("Installed-wheel Book Mode accessibility audit reported an error")
metrics = pdf_audit.get("metrics", {})
if metrics.get("language") != "en-us" or not metrics.get("xmp_metadata"):
    raise SystemExit("Installed-wheel PDF audit did not observe language and XMP metadata")
if metrics.get("compliance_claims", {}).get("pdfua") is not False:
    raise SystemExit("PDF audit must not make an unverified PDF/UA compliance claim")

from pypdf import PdfReader
reader = PdfReader(str(root / "dist" / "book.pdf"))
destinations = set(reader.named_destinations)
for expected in (
    "/xref-fig-model",
    "/xref-tbl-metrics",
    "/xref-eq-energy",
    "/xref-lst-loop",
):
    if expected not in destinations:
        raise SystemExit(f"Cross-reference destination is missing: {expected}")
if len([name for name in destinations if name.startswith("/bib-")]) != 2:
    raise SystemExit("Bibliography destinations are missing from the installed-wheel PDF")
PY_PROJECT
"$venv_bin/mrs-md2pdf-gui" --version
"$venv_bin/mrs-md2pdf-gui" --help | grep -F -- "--project" >/dev/null
"$venv_python" - "$project_smoke" <<'PY_WORKSPACE'
import sys
from pathlib import Path

from mardas_md2pdf.workspace import (
    load_workspace,
    read_workspace_file,
    workspace_payload,
    write_workspace_file,
)

root = Path(sys.argv[1])
workspace = load_workspace(root)
payload = workspace_payload(workspace)
if not payload.get("enabled") or payload.get("book", {}).get("chapter_count") != 2:
    raise SystemExit("Installed-wheel Studio workspace did not load the Book Mode project")
opened = read_workspace_file(workspace, "chapters/01-introduction.md")
saved = write_workspace_file(
    workspace,
    "chapters/01-introduction.md",
    str(opened["content"]),
    expected_sha256=str(opened["sha256"]),
)
if saved.get("sha256") != opened.get("sha256"):
    raise SystemExit("Installed-wheel Studio workspace save was not deterministic")
if any(str(item.get("path", "")).startswith(str(root)) for item in payload.get("diagnostics", [])):
    raise SystemExit("Studio workspace diagnostics exposed an absolute project path")
PY_WORKSPACE
"$venv_python" - "$project_smoke" <<'PY_PERFORMANCE'
import sys
from pathlib import Path

from mardas_md2pdf.render_pool import RenderPool
from mardas_md2pdf.renderer import PdfOptions, RenderSession, convert
from pypdf import PdfReader

root = Path(sys.argv[1])
source = root / "performance-smoke.md"
source.write_text("# Performance smoke\n\nMixed فارسی English.\n", encoding="utf-8")
with RenderSession() as session:
    for index in range(2):
        output = root / f"performance-smoke-{index + 1}.pdf"
        convert(PdfOptions(source, output, cover=False, progress=None), session=session)
        if len(PdfReader(str(output)).pages) != 1:
            raise SystemExit("Persistent-renderer smoke produced an unexpected page count")
    if session.launch_count != 1 or session.page_count != 2:
        raise SystemExit("Persistent-renderer smoke did not reuse one Chromium process")

with RenderPool(workers=1, queue_size=2, idle_timeout=5) as pool:
    first = pool.submit(lambda session, progress, cancelled: id(session))
    second = pool.submit(lambda session, progress, cancelled: id(session))
    if first.result(timeout=10) != second.result(timeout=10):
        raise SystemExit("Render queue did not preserve its thread-affine session")
PY_PERFORMANCE
python scripts/audit_studio_visual.py \
  --project "$project_smoke" \
  --output-dir build/release/studio-project \
  --browser-timeout-ms "${MARDAS_TIMEOUT_MS:-180000}" \
  --clean
python scripts/check_visual_contracts.py \
  --studio-manifest build/release/studio-project/manifest.json \
  --output-dir build/release/visual-contracts/studio-project
"$venv_python" - <<'PY'
from importlib import resources

assets = resources.files("mardas_md2pdf") / "assets"
required = [
    "gui.html",
    "style-modern.css",
    "style-github.css",
    "style-textbook.css",
    "style-academic.css",
    "mardas-md2pdf-mark.svg",
    "mathjax/tex-svg-full.js",
]
missing = [name for name in required if not (assets / name).is_file()]
if missing:
    raise SystemExit(f"Missing packaged assets: {', '.join(missing)}")

for module in ("render_pool.py", "studio_jobs.py"):
    if not (resources.files("mardas_md2pdf") / module).is_file():
        raise SystemExit(f"Missing packaged performance module: {module}")
PY

release_version="$($venv_python -c 'from importlib import metadata; print(metadata.version("mardas-md2pdf"))')"
sdist_path="$(find dist -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
if [[ -z "$sdist_path" ]]; then
  echo "Release gate failed: source distribution was not produced." >&2
  exit 1
fi
source_revision="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
python scripts/generate_sbom.py \
  --python "$venv_python" \
  --distribution mardas-md2pdf \
  --artifact "$wheel_path" \
  --artifact "$sdist_path" \
  --source-revision "$source_revision" \
  --source-date-epoch "$SOURCE_DATE_EPOCH" \
  --output "dist/mardas-md2pdf-${release_version}.spdx.json"
python scripts/finalize_release_artifacts.py \
  --artifact-dir dist \
  --version "$release_version" \
  --source-revision "$source_revision" \
  --source-date-epoch "$SOURCE_DATE_EPOCH" \
  --require-sbom
