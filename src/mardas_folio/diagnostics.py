from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, TextIO

DiagnosticSeverity = Literal["error", "warning", "info"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A stable, machine-readable project diagnostic."""

    code: str
    severity: DiagnosticSeverity
    message: str
    path: Path | None = None
    line: int | None = None
    column: int | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        if self.path is not None:
            data["path"] = str(self.path)
        return {key: value for key, value in data.items() if value is not None}


def has_errors(diagnostics: Iterable[Diagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


def diagnostic_location(item: Diagnostic) -> str:
    if item.path is None:
        return ""
    location = str(item.path)
    if item.line is not None:
        location += f":{item.line}"
        if item.column is not None:
            location += f":{item.column}"
    return location


def format_diagnostic(item: Diagnostic) -> str:
    location = diagnostic_location(item)
    prefix = f"{item.severity.upper()} {item.code}"
    if location:
        prefix += f" {location}"
    text = f"{prefix}: {item.message}"
    if item.hint:
        text += f"\n  Hint: {item.hint}"
    return text


def write_diagnostics(
    diagnostics: Iterable[Diagnostic],
    *,
    output_format: str,
    stream: TextIO,
    context: dict[str, object] | None = None,
) -> None:
    items = list(diagnostics)
    if output_format == "json":
        payload: dict[str, object] = {
            "ok": not has_errors(items),
            "diagnostics": [item.to_dict() for item in items],
        }
        if context:
            payload.update(context)
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        return

    if context:
        for key, value in context.items():
            if value is not None:
                stream.write(f"{key}: {value}\n")
        if items:
            stream.write("\n")
    if not items:
        stream.write("No diagnostics.\n")
        return
    for index, item in enumerate(items):
        if index:
            stream.write("\n")
        stream.write(format_diagnostic(item) + "\n")
