#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "apps" / "desktop" / "frontend" / "index.html"
DEFAULT_OUTPUT = ROOT / "build" / "desktop-accessibility"


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    element: str | None = None


def _element_name(element) -> str:
    if element is None:
        return ""
    identifier = element.get("id")
    if identifier:
        return f"{element.name}#{identifier}"
    classes = ".".join(element.get("class", [])[:3])
    return f"{element.name}{'.' + classes if classes else ''}"


def audit_html(html: str) -> list[Finding]:
    soup = BeautifulSoup(html, "html.parser")
    findings: list[Finding] = []

    html_node = soup.find("html")
    if not html_node or not html_node.get("lang"):
        findings.append(Finding("error", "A11Y-LANG", "The document must declare an interface language.", "html"))
    if not html_node or html_node.get("dir") not in {"rtl", "ltr"}:
        findings.append(Finding("error", "A11Y-DIR", "The document must declare a base text direction.", "html"))

    ids: list[str] = [str(node["id"]) for node in soup.find_all(id=True)]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    for value in duplicates:
        findings.append(Finding("error", "A11Y-DUPLICATE-ID", f"Duplicate id: {value}", f"#{value}"))

    skip = soup.select_one('a.skip-link[href="#app-main"]')
    if skip is None:
        findings.append(Finding("error", "A11Y-SKIP-LINK", "A keyboard skip link to #app-main is required."))

    for button in soup.find_all("button"):
        name = (
            button.get("aria-label")
            or button.get("title")
            or button.get("data-i18n-title")
            or button.get_text(" ", strip=True)
        )
        if not name:
            findings.append(
                Finding("error", "A11Y-BUTTON-NAME", "Button has no accessible name.", _element_name(button))
            )

    for image in soup.find_all("img"):
        if image.get("alt") is None:
            findings.append(
                Finding("error", "A11Y-IMAGE-ALT", "Image is missing an alt attribute.", _element_name(image))
            )

    for control in soup.find_all(["input", "select", "textarea"]):
        labelled = (
            control.get("aria-label")
            or control.get("aria-labelledby")
            or control.get("title")
            or control.find_parent("label") is not None
        )
        if not labelled:
            findings.append(
                Finding(
                    "error",
                    "A11Y-FORM-LABEL",
                    "Form control has no accessible label.",
                    _element_name(control),
                )
            )

    for modal in soup.select('[role="dialog"]'):
        if modal.get("aria-modal") != "true":
            findings.append(
                Finding("error", "A11Y-DIALOG-MODAL", "Dialog must declare aria-modal=true.", _element_name(modal))
            )
        labelledby = modal.get("aria-labelledby")
        label = modal.get("aria-label")
        if not labelledby and not label:
            findings.append(
                Finding("error", "A11Y-DIALOG-NAME", "Dialog must have an accessible name.", _element_name(modal))
            )
        if labelledby and soup.find(id=labelledby) is None:
            findings.append(
                Finding(
                    "error",
                    "A11Y-DIALOG-LABEL-TARGET",
                    f"aria-labelledby references missing id {labelledby}.",
                    _element_name(modal),
                )
            )

    for node in soup.select("[tabindex]"):
        try:
            value = int(str(node.get("tabindex")))
        except ValueError:
            findings.append(
                Finding("error", "A11Y-TABINDEX", "tabindex must be an integer.", _element_name(node))
            )
            continue
        if value > 0:
            findings.append(
                Finding(
                    "error",
                    "A11Y-POSITIVE-TABINDEX",
                    "Positive tabindex creates a fragile custom focus order.",
                    _element_name(node),
                )
            )

    toast = soup.select_one("#toast-region")
    if toast is None or toast.get("aria-live") not in {"polite", "assertive"}:
        findings.append(
            Finding("error", "A11Y-LIVE-REGION", "Toast region must expose an ARIA live region.", "#toast-region")
        )

    return findings


def write_report(findings: list[Finding], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": "passed" if not any(item.severity == "error" for item in findings) else "failed",
        "findings": [asdict(item) for item in findings],
    }
    (output_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Desktop Accessibility Audit",
        "",
        f"Status: **{payload['status'].upper()}**",
        "",
    ]
    if findings:
        lines.extend(
            f"- **{item.severity.upper()} {item.code}** — {item.message}"
            + (f" (`{item.element}`)" if item.element else "")
            for item in findings
        )
    else:
        lines.append("No structural accessibility findings.")
    (output_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit structural accessibility contracts in Mardas Folio.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    findings = audit_html(args.input.read_text(encoding="utf-8"))
    write_report(findings, args.output_dir)
    for item in findings:
        print(f"{item.severity.upper()} {item.code}: {item.message}")
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        print(f"Desktop accessibility audit: FAIL ({len(errors)} errors)")
        return 2
    print("Desktop accessibility audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
