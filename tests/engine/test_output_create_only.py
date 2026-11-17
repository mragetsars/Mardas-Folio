from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pypdf import PdfWriter

from mardas_folio.application import EngineError, EngineService
from mardas_folio.renderer import (
    OutputExistsError,
    RenderCancelledError,
    _atomic_write_pdf,
)


def writer() -> PdfWriter:
    result = PdfWriter()
    result.add_blank_page(width=100, height=100)
    return result


def test_existing_output_is_never_replaced(tmp_path: Path) -> None:
    destination = tmp_path / "existing.pdf"
    destination.write_bytes(b"previous output")
    with pytest.raises(OutputExistsError):
        _atomic_write_pdf(writer(), destination, create_only=True)
    assert destination.read_bytes() == b"previous output"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["existing.pdf"]


def test_concurrent_create_only_exports_have_one_winner(tmp_path: Path) -> None:
    destination = tmp_path / "new.pdf"
    barrier = Barrier(2)

    def export() -> bool:
        barrier.wait()
        try:
            _atomic_write_pdf(writer(), destination, create_only=True)
            return True
        except OutputExistsError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: export(), range(2)))
    assert sorted(outcomes) == [False, True]
    assert destination.read_bytes().startswith(b"%PDF-")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["new.pdf"]


def test_cancellation_before_commit_preserves_existing_output(tmp_path: Path) -> None:
    destination = tmp_path / "existing.pdf"
    destination.write_bytes(b"previous output")
    with pytest.raises(RenderCancelledError):
        _atomic_write_pdf(writer(), destination, create_only=True, cancelled=lambda: True)
    assert destination.read_bytes() == b"previous output"


def test_legacy_callers_can_replace_existing_output(tmp_path: Path) -> None:
    destination = tmp_path / "existing.pdf"
    destination.write_bytes(b"previous output")
    _atomic_write_pdf(writer(), destination)
    assert destination.read_bytes().startswith(b"%PDF-")


def test_desktop_export_inspection_and_existing_output_are_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# A document\n", encoding="utf-8")
    destination = tmp_path / "source.pdf"
    destination.write_bytes(b"prior bytes")
    service = EngineService()
    assert service.dispatch("publication.inspect_output", {"output_path": str(destination)}) == {
        "exists": True
    }
    with pytest.raises(EngineError) as caught:
        service.dispatch(
            "render.document",
            {
                "input_path": str(source),
                "output_path": str(destination),
                "discover_config": False,
                "create_only": True,
            },
        )
    assert caught.value.code == "MARDAS-OUTPUT-EXISTS"
    assert destination.read_bytes() == b"prior bytes"


def test_desktop_export_rejects_auxiliary_outputs_until_protected(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# A document\n", encoding="utf-8")
    destination = tmp_path / "source.pdf"
    report = tmp_path / "quality.json"
    report.write_bytes(b"prior report")
    service = EngineService()
    with pytest.raises(EngineError) as caught:
        service.dispatch(
            "render.document",
            {
                "input_path": str(source),
                "output_path": str(destination),
                "discover_config": False,
                "options": {"quality_report": str(report)},
                "create_only": True,
            },
        )
    assert caught.value.code == "MARDAS-OUTPUT-SIDECAR-UNSUPPORTED"
    assert report.read_bytes() == b"prior report"
    assert not destination.exists()
