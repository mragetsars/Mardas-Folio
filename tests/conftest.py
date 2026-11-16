"""Small opt-in fixtures for application behavior tests."""

from pathlib import Path

import pytest


@pytest.fixture
def engine_service():
    from mardas_folio.application import EngineService

    service = EngineService()
    try:
        yield service
    finally:
        service.close()


@pytest.fixture
def document_factory(tmp_path: Path):
    """Create real files; each test explicitly chooses its content and encoding."""

    def create(name: str = "document.md", content: str = "# Title\n", *, bom=False, crlf=False):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = content.replace("\n", "\r\n") if crlf else content
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        return path

    return create
