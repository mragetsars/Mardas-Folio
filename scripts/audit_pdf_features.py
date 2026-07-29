#!/usr/bin/env python3
"""Render feature-heavy PDF smoke documents for visual QA artifacts."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mardas_md2pdf import __version__  # noqa: E402
from mardas_md2pdf.appearance import MODES, PALETTES_ORDER, STYLES  # noqa: E402
from visual_qa import (  # noqa: E402
    ensure_clean_dir,
    png_stats,
    relative_to,
    render_pdf_pages,
    run_mardas_cli,
    write_html_gallery,
    write_json,
)

FEATURE_SMOKE_MARKDOWN = '---\ntitle: "PDF Feature Smoke"\nsubtitle: "Tables, code, Mermaid, math, captions, footnotes, and RTL/LTR prose"\nauthors:\n  - name: "Mardas MD2PDF QA"\n    role: "Visual smoke"\nsummary: |\n  A compact smoke document that exercises renderer features that have historically\n  needed visual inspection, especially after typography and RTL/Persian changes.\nversion: "__MARDAS_VERSION__"\nlang: en\ndir: ltr\ncover_label: "Feature Smoke"\nbranding:\n  mode: full\n---\n\n# Feature overview\n\nThis sample mixes Persian متن فارسی, English identifiers such as `renderer.pipeline`,\ninline math $a^2 + b^2 = c^2$, a footnote reference[^feature], and a link to\n<https://example.com/path?q=PDF>.\n\n> [!SUCCESS]\n> Callouts should keep their icon, accent, border, and text contrast in every rendered appearance.\n\n## Numbered code block\n\n```python title="qa_matrix.py" linenos linenostart=24 {26,31-32}\ndef build_visual_matrix(styles, palettes, modes):\n    for style in styles:\n        for palette in palettes:\n            for mode in modes:\n                yield f"{style}-{palette}-{mode}"\n\nfor item in build_visual_matrix(["modern"], ["blue"], ["light"]):\n    print(item)\n```\n\n## Captioned table\n\nTable 13. Feature smoke table with mixed Persian and Latin cells.\n\n| Feature | English expectation | یادداشت فارسی | Status |\n| :--- | :--- | :--- | :---: |\n| Code | line numbers stay aligned | شماره خط\u200cها باید هم\u200cراستا باشند | OK |\n| Tables | borders remain visible | جدول نباید clip شود | OK |\n| Math | baseline and display math remain readable | فرمول باید خوانا باشد | OK |\n| Mermaid | node labels and arrows remain visible | نمودار باید کنتراست کافی داشته باشد | OK |\n| RTL text | renderer.[^feature] stays grouped | نشانه\u200cگذاری نباید جابه\u200cجا شود | OK |\n\n## Display math\n\n$$\n\\\\sum_{i=1}^{n} i = \\\\frac{n(n+1)}{2}\n$$\n\n## Mermaid flow\n\n```mermaid title="Render pipeline"\nflowchart LR\n  MD[Markdown] --> HTML[Structured HTML]\n  HTML --> CSS[Appearance CSS]\n  CSS --> PDF[(PDF)]\n  PDF --> QA{{Visual QA}}\n```\n\n## RTL paragraph\n\nدر این پاراگراف فارسی عبارت\u200cهایی مثل renderer. و GitHub Actions. و PDF navigation? باید با نشانه\u200cهای پایانی خود کنار هم بمانند و در خروجی PDF از خط جدا نشوند.\n\n[^feature]: A repeated footnote reference should keep back-links and visual grouping stable.\n'.replace(
    "__MARDAS_VERSION__", __version__
)


@dataclasses.dataclass(frozen=True, slots=True)
class AppearanceCase:
    style: str
    palette: str
    mode: str

    @property
    def name(self) -> str:
        return f"{self.style}-{self.palette}-{self.mode}"


def _parse_appearance(value: str) -> AppearanceCase:
    parts = tuple(part.strip() for part in value.split(":"))
    if len(parts) != 3:
        raise SystemExit(f"invalid appearance {value!r}; expected style:palette:mode")
    style, palette, mode = parts
    if style not in STYLES:
        raise SystemExit(f"invalid style {style!r}; expected one of: {', '.join(STYLES)}")
    if palette not in PALETTES_ORDER:
        raise SystemExit(f"invalid palette {palette!r}; expected one of: {', '.join(PALETTES_ORDER)}")
    if mode not in MODES:
        raise SystemExit(f"invalid mode {mode!r}; expected one of: {', '.join(MODES)}")
    return AppearanceCase(style=style, palette=palette, mode=mode)


def _parse_appearances(value: str | None, *, all_appearances: bool) -> tuple[AppearanceCase, ...]:
    if all_appearances:
        if value:
            raise SystemExit("--all-appearances cannot be combined with --appearances")
        return tuple(AppearanceCase(style, palette, mode) for style in STYLES for palette in PALETTES_ORDER for mode in MODES)
    if not value:
        return (
            AppearanceCase("modern", "blue", "light"),
            AppearanceCase("modern", "blue", "dark"),
            AppearanceCase("github", "slate", "dark"),
            AppearanceCase("academic", "amber", "dark"),
        )
    return tuple(_parse_appearance(part) for part in value.split(",") if part.strip())


def _write_sample(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FEATURE_SMOKE_MARKDOWN, encoding="utf-8")


def _load_existing_records(manifest_path: Path) -> dict[str, dict[str, object]]:
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    records = payload.get("records", [])
    if not isinstance(records, list):
        return {}
    return {str(record.get("name")): record for record in records if isinstance(record, dict) and record.get("name")}


def _record_complete(record: dict[str, object], output_dir: Path, *, render_png: bool) -> bool:
    pdf = record.get("pdf")
    if not isinstance(pdf, str) or not (output_dir / pdf).is_file():
        return False
    if not render_png:
        return True
    images = record.get("png")
    return isinstance(images, list) and all(isinstance(image, str) and (output_dir / image).is_file() for image in images)


def _write_manifest(
    path: Path,
    *,
    source: Path,
    output_dir: Path,
    appearances: tuple[AppearanceCase, ...],
    pages: tuple[int, ...],
    records: dict[str, dict[str, object]],
    failures: list[str],
) -> None:
    ordered_records = [records[name] for name in sorted(records)]
    write_json(
        path,
        {
            "source": relative_to(source, output_dir),
            "appearances": [dataclasses.asdict(case) for case in appearances],
            "pages": pages,
            "counts": {
                "requested": len(appearances),
                "completed": len(ordered_records),
                "failed": len(failures),
            },
            "records": ordered_records,
            "failures": failures,
        },
    )


def _write_gallery(output_dir: Path, records: dict[str, dict[str, object]]) -> None:
    gallery_items = []
    for record in [records[name] for name in sorted(records)]:
        for image in record.get("png", []):
            gallery_items.append(
                {
                    "label": str(record["name"]),
                    "image": str(image),
                    "meta": Path(str(image)).stem,
                }
            )
    write_html_gallery(output_dir / "gallery.html", title="PDF feature smoke", items=gallery_items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("build/visual-qa/features"))
    parser.add_argument("--source", type=Path, help="Use an existing feature smoke Markdown document")
    parser.add_argument(
        "--appearances",
        help="Comma-separated appearance triples: style:palette:mode,style:palette:mode",
    )
    parser.add_argument("--all-appearances", action="store_true", help="Render the feature smoke document for every style/palette/mode")
    parser.add_argument("--clean", action="store_true", help="Delete output directory before rendering")
    parser.add_argument("--resume", action="store_true", help="Reuse completed records from an existing manifest")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first render or rasterization failure")
    parser.add_argument("--max-cases", type=int, help="Limit the number of appearance cases for quick smoke runs")
    parser.add_argument("--render-png", action="store_true", help="Render representative PNG pages")
    parser.add_argument("--png-dpi", type=int, default=72)
    parser.add_argument("--pages", default="1,2,3", help="Comma-separated 1-based PDF pages to rasterize")
    parser.add_argument("--timeout", type=int, default=90, help="Seconds per PDF render")
    parser.add_argument("--timeout-ms", type=int, default=180_000, help="Chromium timeout in milliseconds")
    parser.add_argument("--raster-timeout", type=int, default=60, help="Seconds per pdftoppm page render")
    args = parser.parse_args(argv)

    if args.max_cases is not None and args.max_cases < 1:
        raise SystemExit("--max-cases must be at least 1")
    if args.clean:
        ensure_clean_dir(args.output_dir)
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    appearances = _parse_appearances(args.appearances, all_appearances=args.all_appearances)
    if args.max_cases is not None:
        appearances = appearances[: args.max_cases]
    pages = tuple(int(part.strip()) for part in args.pages.split(",") if part.strip())
    source = args.source or args.output_dir / "feature-smoke.md"
    if args.source is None:
        _write_sample(source)

    pdf_dir = args.output_dir / "pdf"
    png_dir = args.output_dir / "png"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.json"
    records = _load_existing_records(manifest_path) if args.resume else {}
    failures: list[str] = []

    for appearance in appearances:
        existing = records.get(appearance.name)
        if args.resume and existing and _record_complete(existing, args.output_dir, render_png=args.render_png):
            print(f"skip {appearance.name}")
            continue
        output_pdf = pdf_dir / f"{appearance.name}.pdf"
        record: dict[str, object] = {
            "name": appearance.name,
            "style": appearance.style,
            "palette": appearance.palette,
            "mode": appearance.mode,
            "pdf": relative_to(output_pdf, args.output_dir),
        }
        print(f"render {appearance.name}")
        try:
            run_mardas_cli(
                source,
                output_pdf,
                style=appearance.style,
                palette=appearance.palette,
                mode=appearance.mode,
                command_timeout=args.timeout,
                timeout_ms=args.timeout_ms,
            )
            if args.render_png:
                rendered_pages = render_pdf_pages(
                    output_pdf,
                    png_dir,
                    pages=pages,
                    dpi=args.png_dpi,
                    prefix=appearance.name,
                    raster_timeout=args.raster_timeout,
                )
                record["png"] = [relative_to(path, args.output_dir) for path in rendered_pages]
                record["png_stats"] = [dataclasses.asdict(png_stats(path)) for path in rendered_pages]
            records[appearance.name] = record
        except Exception as exc:  # noqa: BLE001 - audit should keep collecting failures.
            failures.append(f"{appearance.name}: {exc}")
            if args.fail_fast:
                _write_manifest(
                    manifest_path,
                    source=source,
                    output_dir=args.output_dir,
                    appearances=appearances,
                    pages=pages,
                    records=records,
                    failures=failures,
                )
                return 1
        _write_manifest(
            manifest_path,
            source=source,
            output_dir=args.output_dir,
            appearances=appearances,
            pages=pages,
            records=records,
            failures=failures,
        )

    if args.render_png:
        _write_gallery(args.output_dir, records)

    if failures:
        (args.output_dir / "failures.txt").write_text("\n".join(failures) + "\n", encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
