"""Filesystem failure tests for the shared commit boundary."""

import os
import stat
from pathlib import Path

import pytest

from mardas_folio import file_io


@pytest.mark.parametrize("failure", [OSError("disk full"), KeyboardInterrupt()])
def test_aborted_commit_preserves_destination_and_cleans_temporary_file(tmp_path, failure):
    target = tmp_path / "report.md"
    target.write_bytes(b"original")

    def reject():
        raise failure

    with pytest.raises(type(failure)):
        file_io.atomic_write_bytes(target, b"replacement", before_replace=reject)
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_io_failure_leaves_original_file_intact(tmp_path, monkeypatch, operation):
    target = tmp_path / "report.md"
    target.write_bytes(b"original")

    def fail(*args):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(file_io.os, operation, fail)
    with pytest.raises(OSError, match="simulated filesystem failure"):
        file_io.atomic_write_text(target, "replacement")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_metadata_describes_our_write_even_when_destination_is_replaced(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    replace = os.replace

    def replace_then_external_edit(source, destination):
        replace(source, destination)
        Path(destination).write_bytes(b"external modification")

    monkeypatch.setattr(file_io.os, "replace", replace_then_external_edit)
    written = file_io.atomic_write_bytes(target, b"ours")
    assert written.st_size == 4
    assert target.read_bytes() == b"external modification"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_replacement_preserves_permissions_and_exact_utf8_bytes(tmp_path):
    target = tmp_path / "report.md"
    target.write_bytes(b"original")
    target.chmod(0o640)
    file_io.atomic_write_text(target, "\ufeffسلام\r\nEnglish\r\n")
    assert target.read_bytes() == "\ufeffسلام\r\nEnglish\r\n".encode()
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_directory_sync_is_best_effort_after_successful_commit(tmp_path, monkeypatch):
    target = tmp_path / "report.md"
    fsync = os.fsync

    def reject_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("directory sync unsupported")
        fsync(descriptor)

    monkeypatch.setattr(file_io.os, "fsync", reject_directory)
    file_io.atomic_write_text(target, "committed")
    assert target.read_text() == "committed"


def test_stream_initialization_failure_closes_the_allocated_descriptor(tmp_path, monkeypatch):
    descriptors = []

    def reject_stream(descriptor, *args):
        descriptors.append(descriptor)
        raise OSError("stream unavailable")

    monkeypatch.setattr(file_io.os, "fdopen", reject_stream)
    with pytest.raises(OSError, match="stream unavailable"):
        file_io.atomic_write_bytes(tmp_path / "document.md", b"new")
    assert not list(tmp_path.iterdir())
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
