#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

output="${MARDAS_SECURITY_AUDIT_OUTPUT:-build/security/pip-audit.json}"
output_dir="$(dirname -- "$output")"
output_name="$(basename -- "$output")"
if [[ "$output" == */ || "$output_name" == "." || "$output_name" == ".." || "$output_name" == "/" ]]; then
  echo "Refusing invalid dependency-audit output path: $output" >&2
  exit 2
fi
mkdir -p -- "$output_dir"
if [[ -L "$output" || ( -e "$output" && ! -f "$output" ) ]]; then
  echo "Refusing non-regular dependency-audit output path: $output" >&2
  exit 2
fi

# A failed rerun must not leave a previous successful report looking current.
rm -f -- "$output"
audit_tmp="$(mktemp -d "${TMPDIR:-/tmp}/mardas-pip-audit.XXXXXX")"
audit_result="$(mktemp "$output_dir/.pip-audit-result.XXXXXX")"
trap 'rm -rf -- "$audit_tmp"; rm -f -- "$audit_result"' EXIT
requirements="$audit_tmp/requirements.txt"
editables="$audit_tmp/editables.json"

# The checkout itself is intentionally editable in CI. Refuse to silently skip
# any other editable dependency, then preserve the exact installed pins without
# asking pip-audit to create a resolver environment.
python -m pip list --editable --format=json > "$editables"
python - "$repo_root" "$editables" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


root = Path(sys.argv[1]).resolve(strict=True)
inventory = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if len(inventory) != 1 or canonical_name(str(inventory[0].get("name", ""))) != "mardas-folio":
    raise SystemExit("Expected only the Mardas checkout to be installed as editable.")
location = inventory[0].get("editable_project_location")
if not location or Path(location).resolve(strict=True) != root:
    raise SystemExit("The editable Mardas installation does not point at this checkout.")
PY

python -m pip freeze --all --exclude-editable > "$requirements"
test -s "$requirements"
python - "$requirements" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement


for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    try:
        requirement = Requirement(line)
    except InvalidRequirement as exc:
        raise SystemExit(f"Unparseable installed dependency pin: {line!r}") from exc
    specifiers = list(requirement.specifier)
    exact_pin = (
        requirement.url is None
        and requirement.marker is None
        and not requirement.extras
        and len(specifiers) == 1
        and specifiers[0].operator in {"==", "==="}
        and "*" not in specifiers[0].version
    )
    if not exact_pin:
        raise SystemExit(f"Installed dependency is not an exact registry pin: {line!r}")
PY

python -m pip_audit \
  --strict \
  --no-deps \
  --disable-pip \
  --requirement "$requirements" \
  --format json \
  --output "$audit_result"
mv -f -- "$audit_result" "$output"
echo "Dependency audit written to $output"
