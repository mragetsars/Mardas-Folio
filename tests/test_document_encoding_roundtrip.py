from pathlib import Path

import pytest

from mardas_folio import application


@pytest.mark.parametrize("bom,newline", [(b"", b"\n"), (b"\xef\xbb\xbf", b"\r\n")])
def test_existing_document_preserves_encoding_on_noop_and_edit(tmp_path: Path, bom: bytes, newline: bytes):
    path = tmp_path / "سند.md"
    original = bom + newline.join([b"# Title", b"First", b""])
    path.write_bytes(original)
    opened = application.read_document(path)
    initial_stat = path.stat()
    # Web editors commonly normalize line breaks to LF before a save.
    content = opened["content"].replace("\r\n", "\n")
    saved = application.save_document(path, content, expected_revision=opened["revision"])
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == initial_stat.st_mtime_ns
    application.save_document(path, content + "Added\n", expected_revision=saved["revision"])
    assert path.read_bytes() == original + b"Added" + newline


def test_mixed_newlines_preserved_on_noop_and_normalized_after_edit(tmp_path: Path):
    path = tmp_path / "mixed.md"
    original = b"one\r\ntwo\nthree\r"
    path.write_bytes(original)
    opened = application.read_document(path)
    content = opened["content"].replace("\r\n", "\n").replace("\r", "\n")
    saved = application.save_document(path, content, expected_revision=opened["revision"])
    assert path.read_bytes() == original
    application.save_document(path, content + "four\n", expected_revision=saved["revision"])
    assert path.read_bytes() == b"one\ntwo\nthree\nfour\n"
