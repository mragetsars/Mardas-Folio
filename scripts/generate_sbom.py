#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from release_provenance import (
    PROJECT_NAME,
    ReleaseProvenanceError,
    generate_spdx_document,
    query_installed_distributions,
    runtime_dependency_closure,
    source_date_epoch,
    validate_spdx_document,
    write_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deterministic SPDX 2.3 runtime SBOM")
    parser.add_argument(
        "--python", type=Path, default=Path(sys.executable), help="Python environment to inspect"
    )
    parser.add_argument("--distribution", default=PROJECT_NAME, help="Root installed distribution")
    parser.add_argument(
        "--artifact", action="append", type=Path, default=[], help="Release artifact to bind"
    )
    parser.add_argument("--output", required=True, type=Path, help="Output SPDX JSON path")
    parser.add_argument("--source-revision", default="unknown", help="Source Git revision")
    parser.add_argument("--source-date-epoch", help="Deterministic creation timestamp")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = query_installed_distributions(args.python)
        selected, relationships = runtime_dependency_closure(records, args.distribution)
        root = next(
            item
            for item in selected
            if item.name.lower().replace("_", "-") == args.distribution.lower().replace("_", "-")
        )
        payload = generate_spdx_document(
            distributions=selected,
            relationships=relationships,
            artifact_paths=args.artifact,
            root_name=args.distribution,
            source_revision=args.source_revision,
            epoch=source_date_epoch(args.source_date_epoch),
        )
        validate_spdx_document(payload, expected_version=root.version)
        write_json(args.output, payload)
    except (ReleaseProvenanceError, OSError) as exc:
        print(f"SBOM generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"SPDX SBOM written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
