#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

output="${MARDAS_SECURITY_AUDIT_OUTPUT:-build/security/pip-audit.json}"
mkdir -p "$(dirname "$output")"
python -m pip_audit --local --strict --format json --output "$output"
echo "Dependency audit written to $output"
