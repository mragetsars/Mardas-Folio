from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mardas_folio import application
from mardas_folio.application import EngineError
from mardas_folio.renderer import RenderCancelledError


def test_import_unicode_and_existing_names(tmp_path: Path) -> None:
    document = tmp_path / "سند.md"
    document.write_text("# Test", encoding="utf-8")
    source = tmp_path / "عکس.png"
    source.write_bytes(b"new image")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / source.name).write_bytes(b"existing image")

    result = application.import_document_asset(document, source)
    assert result["name"] == "عکس-2.png"
    assert (assets / source.name).read_bytes() == b"existing image"
    assert (assets / result["name"]).read_bytes() == b"new image"
    assert application.import_document_asset(document, source)["name"] == "عکس-2.png"


def test_discovery_skips_nested_link_and_honours_cancellation(tmp_path: Path) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    document = root / "test.md"
    document.write_text("# Test", encoding="utf-8")
    local = root / "assets"
    local.mkdir()
    (local / "local.png").write_bytes(b"local")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"outside")
    try:
        (local / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic link creation is unavailable")

    result = application.list_document_assets(document)
    assert [asset["relative_path"] for asset in result["assets"]] == ["assets/local.png"]
    with pytest.raises(RenderCancelledError):
        application.list_document_assets(document, cancelled=lambda: True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor regression")
def test_import_rejects_directory_swap_before_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    document = root / "test.md"
    document.write_text("# Test", encoding="utf-8")
    source = tmp_path / "image.png"
    source.write_bytes(b"new image")
    target = root / "assets"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_fsync = application.os.fsync

    def swap_after_write(descriptor: int) -> None:
        original_fsync(descriptor)
        target.rename(root / "original-assets")
        target.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(application.os, "fsync", swap_after_write)
    with pytest.raises(EngineError):
        application.import_document_asset(document, source)
    assert not (outside / "image.png").exists()
    assert not list((root / "original-assets").iterdir())


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS junction regression")
def test_windows_junction_root_and_nested_are_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "اسناد"
    root.mkdir()
    document = root / "document.md"
    document.write_text("# Test", encoding="utf-8")
    source = tmp_path / "image.png"
    source.write_bytes(b"new image")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "existing.png").write_bytes(b"outside")
    junction = root / "assets"

    def make_junction(path: Path) -> None:
        env = dict(os.environ, MARDAS_TEST_JUNCTION=str(path), MARDAS_TEST_TARGET=str(outside))
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "New-Item -ItemType Junction -Path $env:MARDAS_TEST_JUNCTION "
             "-Target $env:MARDAS_TEST_TARGET -ErrorAction Stop | Out-Null"],
            env=env, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            pytest.skip(f"Junction creation unavailable: {result.stderr}")

    make_junction(junction)
    assert application.list_document_assets(document)["assets"] == []
    with pytest.raises(EngineError) as error:
        application.import_document_asset(document, source)
    assert error.value.code == "MARDAS-ASSET-INVALID"
    assert not (outside / "image.png").exists()

    junction.rmdir()
    junction.mkdir()
    make_junction(junction / "nested")
    assert application.list_document_assets(document)["assets"] == []
    imported = application.import_document_asset(document, source)
    assert imported["relative_path"] == "assets/image.png"
    assert (root / "assets" / "image.png").read_bytes() == b"new image"
    assert not (junction / "image.png").exists()
    assert not (outside / "image.png").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-handle regression")
def test_windows_import_keeps_assets_directory_anchored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    document = root / "test.md"
    document.write_text("# Test", encoding="utf-8")
    source = tmp_path / "image.png"
    source.write_bytes(b"new image")
    target = root / "assets"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_fsync = application.os.fsync
    rename_blocked = False

    def attempt_swap_after_write(descriptor: int) -> None:
        nonlocal rename_blocked
        original_fsync(descriptor)
        try:
            target.rename(root / "original-assets")
        except OSError:
            rename_blocked = True
            return
        target.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(application.os, "fsync", attempt_swap_after_write)
    imported = application.import_document_asset(document, source)
    assert rename_blocked
    assert imported["relative_path"] == "assets/image.png"
    assert (target / "image.png").read_bytes() == b"new image"
    assert not (outside / "image.png").exists()
