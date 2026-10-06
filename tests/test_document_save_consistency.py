from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from mardas_folio import application, workspace


def test_document_read_revision_describes_the_returned_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "report.md"
    path.write_text("# Original\n", encoding="utf-8")
    read_snapshot = application._document_snapshot

    def replace_after_snapshot(source: Path):
        snapshot = read_snapshot(source)
        source.write_text("# External edit\n", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(application, "_document_snapshot", replace_after_snapshot)
    opened = application.read_document(path)
    monkeypatch.setattr(application, "_document_snapshot", read_snapshot)

    assert opened["content"] == "# Original\n"
    assert opened["revision"] != application._document_revision(path)
    with pytest.raises(application.EngineError) as error:
        application.save_document(path, "# Editor\n", expected_revision=opened["revision"])
    assert error.value.code == "MARDAS-DOCUMENT-CONFLICT"
    assert path.read_text(encoding="utf-8") == "# External edit\n"


def test_document_save_detects_changes_during_temporary_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "report.md"
    path.write_text("# Original\n", encoding="utf-8")
    opened = application.read_document(path)
    real_fsync = application.os.fsync

    def external_edit_after_flush(descriptor: int) -> None:
        real_fsync(descriptor)
        path.write_text("# External edit\n", encoding="utf-8")

    monkeypatch.setattr(application.os, "fsync", external_edit_after_flush)
    with pytest.raises(application.EngineError) as error:
        application.save_document(path, "# Editor\n", expected_revision=opened["revision"])
    assert error.value.code == "MARDAS-DOCUMENT-CONFLICT"
    assert path.read_text(encoding="utf-8") == "# External edit\n"
    assert list(tmp_path.iterdir()) == [path]


def test_concurrent_document_saves_do_not_both_replace_the_same_revision(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("# Original\n", encoding="utf-8")
    revision = application.read_document(path)["revision"]
    ready = Barrier(2)

    def save(content: str) -> str:
        ready.wait(timeout=5)
        try:
            application.save_document(path, content, expected_revision=revision)
            return "saved"
        except application.EngineError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ["# First\n", "# Second\n"]))
    assert sorted(results) == ["MARDAS-DOCUMENT-CONFLICT", "saved"]


def test_workspace_save_detects_changes_during_temporary_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mardas.toml").write_text("schema_version = 1\n", encoding="utf-8")
    path = tmp_path / "report.md"
    path.write_text("# Original\n", encoding="utf-8")
    project = workspace.load_workspace(tmp_path)
    opened = workspace.read_workspace_file(project, "report.md")
    real_fsync = workspace.os.fsync

    def external_edit_after_flush(descriptor: int) -> None:
        real_fsync(descriptor)
        path.write_text("# External edit\n", encoding="utf-8")

    monkeypatch.setattr(workspace.os, "fsync", external_edit_after_flush)
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.write_workspace_file(
            project, "report.md", "# Editor\n", expected_sha256=str(opened["sha256"])
        )
    assert error.value.code == "project_file_changed"
    assert path.read_text(encoding="utf-8") == "# External edit\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["mardas.toml", "report.md"]


def test_workspace_save_response_describes_written_buffer_after_external_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mardas.toml").write_text("schema_version = 1\n", encoding="utf-8")
    path = tmp_path / "report.md"
    path.write_text("# Original\n", encoding="utf-8")
    project = workspace.load_workspace(tmp_path)
    opened = workspace.read_workspace_file(project, "report.md")
    real_replace = workspace.os.replace

    def external_edit_after_replace(source, target):
        real_replace(source, target)
        Path(target).write_text("# External edit\n", encoding="utf-8")

    monkeypatch.setattr(workspace.os, "replace", external_edit_after_replace)
    saved = workspace.write_workspace_file(
        project, "report.md", "# Editor\n", expected_sha256=str(opened["sha256"])
    )
    assert saved["content"] == "# Editor\n"
    assert saved["sha256"] != workspace.read_workspace_file(project, "report.md")["sha256"]
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.write_workspace_file(
            project, "report.md", "# Next edit\n", expected_sha256=str(saved["sha256"])
        )
    assert error.value.code == "project_file_changed"
