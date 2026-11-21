"""Measure the two primary paragraphs in the printed typography examples."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import median
from typing import Any

import pymupdf


def _body_lines(page: Any, size: float) -> list[dict[str, Any]]:
    spans_by_baseline: dict[float, list[dict[str, Any]]] = {}
    for block in page.get_text(
        "dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    )["blocks"]:
        for line in block.get("lines", ()):
            for span in line["spans"]:
                if span["text"] and abs(span["size"] - size) < 0.35:
                    spans_by_baseline.setdefault(round(span["origin"][1], 1), []).append(span)
    # Combining marks can have a different origin from the rest of a word.
    # Group them with the dominant baseline and retain the PDF's reading order.
    baselines: list[float] = []
    for origin in sorted(
        spans_by_baseline,
        key=lambda key: -sum(len(span["text"].strip()) for span in spans_by_baseline[key]),
    ):
        if all(abs(origin - baseline) > 3.8 for baseline in baselines):
            baselines.append(origin)
    by_baseline: dict[float, list[dict[str, Any]]] = {origin: [] for origin in baselines}
    for origin, spans in spans_by_baseline.items():
        by_baseline[min(baselines, key=lambda baseline: abs(origin - baseline))].extend(spans)
    return [
        {
            "text": "".join(span["text"] for span in spans),
            "y": y,
            "left": min(span["bbox"][0] for span in spans),
            "right": max(span["bbox"][2] for span in spans),
            "size": median(span["size"] for span in spans),
            "fonts": {span["font"] for span in spans},
        }
        for y, spans in sorted(by_baseline.items())
    ]


def _paragraph(lines: list[dict[str, Any]], start: int, leading_pt: float) -> dict[str, Any]:
    segment = [lines[start]]
    for line in lines[start + 1 :]:
        delta = line["y"] - segment[-1]["y"]
        if not 0.55 * leading_pt < delta < 1.32 * leading_pt:
            break
        segment.append(line)
    if len(segment) < 3:
        raise ValueError("The sample paragraph did not provide enough measured lines")
    full = segment[:-1]
    spacing = [next_line["y"] - line["y"] for line, next_line in zip(segment, segment[1:])]
    widths = [line["right"] - line["left"] for line in segment]
    # PDF rectangles are ink bounds. Arabic glyph bearings and embedded
    # fallback spans can differ even when the advance reaches the margin.
    return {
        "body_size_pt": round(median(line["size"] for line in segment), 3),
        "font_names": sorted(set().union(*(line["fonts"] for line in segment))),
        "baseline_step_pt": round(median(spacing), 2),
        "first_line_baseline_pt": round(segment[0]["y"], 2),
        "line_widths_pt": [round(width, 2) for width in widths],
        "full_line_edges_pt": [[round(line["left"], 2), round(line["right"], 2)] for line in full],
        "inner_left_spread_pt": round(
            max(ln["left"] for ln in full) - min(ln["left"] for ln in full), 2
        ),
        "inner_right_spread_pt": round(
            max(ln["right"] for ln in full) - min(ln["right"] for ln in full), 2
        ),
        "last_line_width_ratio": round(widths[-1] / median(widths[:-1]), 3),
    }


def measure(path: Path, size: float, leading: float) -> dict[str, Any]:
    paragraphs = {}
    with pymupdf.open(path) as pdf:
        for page in pdf:
            lines = _body_lines(page, size)
            for index, line in enumerate(lines):
                text = line["text"]
                if "The typesetting proof" in text:
                    paragraphs["en"] = {
                        "page": page.number + 1,
                        **_paragraph(lines, index, size * leading),
                    }
                if re.search(r"این\s+بند\s+فارسی|در\s+این\s+بند", text):
                    paragraphs["fa"] = {
                        "page": page.number + 1,
                        **_paragraph(lines, index, size * leading),
                    }
        if set(paragraphs) != {"en", "fa"}:
            raise ValueError(f"Bilingual paragraph markers were not found in {path}")
        return {
            "file": str(path),
            "pages": len(pdf),
            "requested_size_pt": size,
            "requested_leading": leading,
            "paragraphs": paragraphs,
            "embedded_font_names": sorted(
                {
                    name
                    for page in pdf
                    for _, ext, _, name, *_ in page.get_fonts()
                    if ext != "n/a" and name
                }
            ),
            "sample_links": sorted(
                {link["uri"] for page in pdf for link in page.get_links() if link.get("uri")}
            ),
            "fixed_marks": {
                label: {
                    "page": page.number + 1,
                    "left_pt": round(rect.x0, 2),
                    "right_pt": round(rect.x1, 2),
                    "height_pt": round(rect.height, 2),
                }
                for label in (
                    "12",
                    "keep two spaces",
                    "Specimen table with numeric column.",
                    "Generated Document",
                    "Type specimen",
                )
                for page in pdf
                for rect in page.search_for(label)
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("small", type=Path)
    parser.add_argument("large", type=Path)
    parser.add_argument("--leading", type=float, default=1.6)
    args = parser.parse_args()
    results = [measure(args.small, 11, args.leading), measure(args.large, 14, args.leading)]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if any(evidence["sample_links"] != ["https://example.com/guide"] for evidence in results):
        raise SystemExit("The bilingual URL was not retained as a link")
    for label in (
        "12",
        "keep two spaces",
        "Specimen table with numeric column.",
        "Generated Document",
        "Type specimen",
    ):
        one, two = (evidence["fixed_marks"].get(label) for evidence in results)
        if (
            not one
            or not two
            or any(abs(one[key] - two[key]) > 0.5 for key in ("left_pt", "right_pt", "height_pt"))
        ):
            raise SystemExit(f"Changing body size moved or resized {label!r}")
    for result in results:
        expected = result["requested_size_pt"]
        for para in result["paragraphs"].values():
            if (
                not any("Vazirmatn" in name for name in para["font_names"])
                or abs(para["body_size_pt"] - expected) > 0.35
                or abs(para["baseline_step_pt"] - expected * args.leading) > 1.2
                or para["last_line_width_ratio"] >= 0.995
            ):
                raise SystemExit("Measured body size, baseline spacing, or last-line width failed")
        if result["paragraphs"]["en"]["inner_right_spread_pt"] > 1.5:
            raise SystemExit("The English full lines did not align to the right margin")
        if result["paragraphs"]["en"]["inner_left_spread_pt"] > 1.5:
            raise SystemExit("The English full lines did not align to the left margin")
        if result["paragraphs"]["fa"]["inner_right_spread_pt"] > 1.5:
            raise SystemExit("The Persian full lines did not align to the right margin")
        if result["paragraphs"]["fa"]["inner_left_spread_pt"] > 3.5:
            raise SystemExit("The Persian full lines did not align to the left margin")


if __name__ == "__main__":
    main()
