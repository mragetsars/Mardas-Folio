#!/usr/bin/env python3
"""Validate semantic contracts for generated visual-QA artifacts.

The checker deliberately avoids committing machine-specific PNG baselines. It gates the
parts that should remain stable across Chromium, font rasterizers, and operating systems:
complete manifests, non-empty images, plausible page dimensions/ink coverage, and the
Studio interaction checks emitted by ``audit_studio_visual.py``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from visual_qa import png_stats, read_png, write_json


@dataclass(frozen=True, slots=True)
class ContractFailure:
    source: str
    message: str


def _read_manifest(path: Path, failures: list[ContractFailure]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        failures.append(ContractFailure(str(path), "manifest does not exist"))
        return {}
    except json.JSONDecodeError as exc:
        failures.append(ContractFailure(str(path), f"invalid JSON: {exc}"))
        return {}
    if not isinstance(payload, dict):
        failures.append(ContractFailure(str(path), "manifest root must be a JSON object"))
        return {}
    return payload


def _validate_image(
    manifest: Path,
    relative: object,
    failures: list[ContractFailure],
    *,
    label: str,
    minimum_width: int,
    minimum_height: int,
) -> None:
    if not isinstance(relative, str) or not relative.strip():
        failures.append(ContractFailure(str(manifest), f"{label} path is missing"))
        return
    image = (manifest.parent / relative).resolve()
    try:
        image.relative_to(manifest.parent.resolve())
    except ValueError:
        failures.append(ContractFailure(str(manifest), f"{label} escapes the audit directory"))
        return
    if not image.is_file():
        failures.append(ContractFailure(str(manifest), f"{label} does not exist: {relative}"))
        return
    try:
        stats = png_stats(image)
    except (OSError, ValueError) as exc:
        failures.append(ContractFailure(str(manifest), f"{label} is not a readable PNG: {exc}"))
        return
    if stats.width < minimum_width or stats.height < minimum_height:
        failures.append(
            ContractFailure(
                str(manifest),
                f"{label} is unexpectedly small: {stats.width}x{stats.height}",
            )
        )
    if not 0.001 <= stats.dark_ratio + stats.light_ratio <= 1.0:
        failures.append(ContractFailure(str(manifest), f"{label} has implausible pixel ratios"))
    # A completely uniform raster often means a blank PDF page, failed iframe, or clipping.
    if len(set(read_png(image).pixels)) == 1:
        failures.append(ContractFailure(str(manifest), f"{label} is a uniform/blank raster"))


def _manifest_failures(payload: dict[str, Any]) -> list[str]:
    values = payload.get("failures", [])
    if not isinstance(values, list):
        return ["manifest failures field is not a list"]
    return [str(value) for value in values if str(value).strip()]


def validate_appearance_manifest(path: Path, failures: list[ContractFailure]) -> int:
    payload = _read_manifest(path, failures)
    matrix = payload.get("matrix", {})
    records = payload.get("records", [])
    if not isinstance(matrix, dict) or not isinstance(records, list):
        failures.append(ContractFailure(str(path), "appearance manifest shape is invalid"))
        return 0
    recorded_failures = _manifest_failures(payload)
    if recorded_failures or int(matrix.get("failed") or 0):
        failures.append(ContractFailure(str(path), "appearance audit contains failed cases"))
    completed = int(matrix.get("completed") or 0)
    if completed != len(records) or completed < 1:
        failures.append(
            ContractFailure(
                str(path),
                f"appearance completion mismatch: completed={completed}, records={len(records)}",
            )
        )
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            failures.append(ContractFailure(str(path), f"appearance record {index} is invalid"))
            continue
        _validate_image(
            path,
            record.get("cover_png"),
            failures,
            label=f"appearance record {index} cover",
            minimum_width=250,
            minimum_height=300,
        )
        _validate_image(
            path,
            record.get("content_png"),
            failures,
            label=f"appearance record {index} content",
            minimum_width=250,
            minimum_height=300,
        )
    return len(records)


def validate_features_manifest(path: Path, failures: list[ContractFailure]) -> int:
    payload = _read_manifest(path, failures)
    counts = payload.get("counts", {})
    records = payload.get("records", [])
    if not isinstance(counts, dict) or not isinstance(records, list):
        failures.append(ContractFailure(str(path), "feature manifest shape is invalid"))
        return 0
    if _manifest_failures(payload) or int(counts.get("failed") or 0):
        failures.append(ContractFailure(str(path), "feature audit contains failed cases"))
    completed = int(counts.get("completed") or 0)
    requested = int(counts.get("requested") or 0)
    if completed != len(records) or requested != completed or completed < 1:
        failures.append(
            ContractFailure(
                str(path),
                f"feature completion mismatch: requested={requested}, completed={completed}, records={len(records)}",
            )
        )
    image_count = 0
    for record_index, record in enumerate(records):
        images = record.get("png", []) if isinstance(record, dict) else []
        if not isinstance(images, list) or not images:
            failures.append(ContractFailure(str(path), f"feature record {record_index} has no PNG pages"))
            continue
        for page_index, image in enumerate(images):
            _validate_image(
                path,
                image,
                failures,
                label=f"feature record {record_index} page {page_index + 1}",
                minimum_width=250,
                minimum_height=300,
            )
            image_count += 1
    return image_count


STUDIO_REQUIRED_CHECKS = (
    "export_button_visible",
    "document_section_visible",
    "appearance_section_visible",
    "branding_section_visible",
    "publication_quality_section_present",
    "preview_frame_visible",
    "pdf_like_preview_css_loaded",
    "pdf_like_page_guides_removed",
    "long_editor_line_numbers_ok",
    "pdf_like_scroll_sync_removed",
    "fast_scroll_sync_guarded",
    "toast_region_present",
    "command_palette_navigation",
    "export_queue_helpers",
    "cancel_export_button_present",
    "preview_status_unclipped",
    "preview_status_unclipped_live",
)


def validate_studio_manifest(path: Path, failures: list[ContractFailure]) -> int:
    payload = _read_manifest(path, failures)
    checks = payload.get("checks", {})
    if not isinstance(checks, dict):
        failures.append(ContractFailure(str(path), "Studio checks must be a JSON object"))
        return 0
    if checks.get("title") != "Mardas Folio":
        failures.append(ContractFailure(str(path), "unexpected Studio title"))
    if checks.get("preview_mode") != "accurate" or checks.get("preview_failed"):
        failures.append(ContractFailure(str(path), "Studio PDF-like preview did not become ready"))
    for key in STUDIO_REQUIRED_CHECKS:
        if checks.get(key) is not True:
            failures.append(ContractFailure(str(path), f"Studio contract failed: {key}"))
    _validate_image(
        path,
        payload.get("screenshot"),
        failures,
        label="Studio screenshot",
        minimum_width=800,
        minimum_height=500,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appearance-manifest", type=Path)
    parser.add_argument("--features-manifest", type=Path)
    parser.add_argument("--studio-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("build/visual-contracts"))
    args = parser.parse_args(argv)

    manifests = [args.appearance_manifest, args.features_manifest, args.studio_manifest]
    if not any(manifests):
        parser.error("at least one visual manifest must be provided")

    failures: list[ContractFailure] = []
    counts = {"appearance_records": 0, "feature_images": 0, "studio_manifests": 0}
    if args.appearance_manifest:
        counts["appearance_records"] = validate_appearance_manifest(
            args.appearance_manifest, failures
        )
    if args.features_manifest:
        counts["feature_images"] = validate_features_manifest(args.features_manifest, failures)
    if args.studio_manifest:
        counts["studio_manifests"] = validate_studio_manifest(args.studio_manifest, failures)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "ok": not failures,
        "counts": counts,
        "failures": [asdict(item) for item in failures],
    }
    write_json(args.output_dir / "summary.json", payload)
    lines = ["# Visual contract report", "", f"Status: **{'PASS' if not failures else 'FAIL'}**", ""]
    lines.extend(f"- {name}: {value}" for name, value in counts.items())
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{item.source}`: {item.message}" for item in failures)
    (args.output_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failures:
        for item in failures:
            print(f"FAIL {item.source}: {item.message}")
        return 1
    print(f"Visual contracts passed; report: {args.output_dir / 'SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
