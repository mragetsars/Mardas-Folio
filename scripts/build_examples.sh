#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1735689600}"
mkdir -p examples

python - <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from visual_qa import run_command  # noqa: E402

repo_root = Path.cwd()
timeout_ms = int(os.environ.get("MARDAS_TIMEOUT_MS", "180000"))
command_timeout = int(os.environ.get("MARDAS_BUILD_EXAMPLES_COMMAND_TIMEOUT", str(max(120, timeout_ms // 1000 + 60))))

examples = [
    ("docs/guides/GUIDE.en.md", "examples/GUIDE.en.pdf"),
    ("docs/guides/GUIDE.fa.md", "examples/GUIDE.fa.pdf"),
]

for source, output in examples:
    command = [
        sys.executable,
        "-m",
        "mardas_folio.cli",
        source,
        "-o",
        output,
        "--toc",
        "--style",
        "modern",
        "--palette",
        "emerald",
        "--mode",
        "light",
        "--timeout-ms",
        str(timeout_ms),
        "--progress",
        "off",
    ]
    print(f"[build_examples] Rendering {output}", flush=True)
    completed = run_command(command, timeout=command_timeout, description=f"guide render for {output}")
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
PY
