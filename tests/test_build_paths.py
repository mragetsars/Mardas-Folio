from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_paths import MARKER, prepare_output, validate_output  # noqa: E402
from build_publish import publish_directory, publish_verified  # noqa: E402


def test_clean_rejects_sources_ancestors_and_unowned_content(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    source = workspace / "src"
    source.mkdir()
    outside = tmp_path / "personal"
    outside.mkdir()
    sentinel = outside / "document.md"
    sentinel.write_text("valuable", encoding="utf-8")
    for output in (workspace, source, tmp_path, Path.home(), outside):
        with pytest.raises(ValueError):
            prepare_output(output, workspace=workspace, clean=True)
    assert sentinel.read_text(encoding="utf-8") == "valuable"
    assert source.is_dir()


def test_owned_outputs_can_be_rebuilt_and_no_clean_preserves_files(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    output = prepare_output(tmp_path / "output", workspace=workspace, clean=True)
    artifact = output / "old.bin"
    artifact.write_bytes(b"old")
    prepare_output(output, workspace=workspace, clean=False)
    assert artifact.read_bytes() == b"old"
    prepare_output(output, workspace=workspace, clean=True)
    assert not artifact.exists()
    assert (output / MARKER).is_file()


def test_no_clean_never_claims_an_unowned_directory(tmp_path: Path) -> None:
    output = tmp_path / "personal"
    output.mkdir()
    (output / "document.md").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned"):
        prepare_output(output, workspace=tmp_path / "other", clean=False)
    assert not (output / MARKER).exists()


def test_clean_protects_runtime_inputs_and_symlink_aliases(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    browser = workspace / "build" / "browser"
    browser.mkdir(parents=True)
    with pytest.raises(ValueError, match="overlaps"):
        prepare_output(browser.parent, workspace=workspace, clean=True, protected=(browser,))
    link = tmp_path / "alias"
    try:
        link.symlink_to(browser, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        validate_output(link / "child", workspace=workspace)
    assert browser.is_dir()


def test_failed_verification_keeps_prior_artifact_and_unrelated_temporary(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"invalid")
    final = tmp_path / "release.exe"
    final.write_bytes(b"previous-good")
    neighbor = tmp_path / "release.exe.tmp"
    neighbor.write_bytes(b"unrelated")

    def verify(staged: Path) -> None:
        assert staged.name == final.name
        assert staged.read_bytes() == b"invalid"
        raise ValueError("invalid build")

    with pytest.raises(ValueError, match="invalid build"):
        publish_verified(candidate, final, verify)
    assert final.read_bytes() == b"previous-good"
    assert neighbor.read_bytes() == b"unrelated"
    assert not list(tmp_path.glob(".mardas-publish-*"))


def test_incremental_marker_write_never_follows_a_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    output = workspace / "build" / "output"
    output.mkdir(parents=True)
    source = workspace / "document.md"
    source.write_text("keep", encoding="utf-8")
    try:
        (output / MARKER).symlink_to(source)
    except OSError:
        pytest.skip("symlinks unavailable")
    prepare_output(output, workspace=workspace, clean=False)
    assert source.read_text(encoding="utf-8") == "keep"
    assert not (output / MARKER).is_symlink()


def test_runtime_promotion_restores_prior_build_after_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    produced = tmp_path / "produced"
    produced.mkdir()
    (produced / "engine").write_bytes(b"new")
    final = tmp_path / "runtime"
    final.mkdir()
    (final / "engine").write_bytes(b"good")
    original = Path.replace

    def fail_promotion(path: Path, target: Path) -> Path:
        if path == produced:
            raise OSError("promotion failed")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_promotion)
    with pytest.raises(OSError, match="promotion failed"):
        publish_directory(produced, final, lambda path: None)
    assert (final / "engine").read_bytes() == b"good"
    assert (produced / "engine").read_bytes() == b"new"
    assert not list(tmp_path.glob(".mardas-runtime-backup-*"))
