from __future__ import annotations

import os
from pathlib import Path

import pytest

from mardas_folio import application, sidecar
from mardas_folio.application import EngineError, EngineService
from mardas_folio.workspace import (
    WorkspaceError,
    add_workspace_book_chapter,
    create_book_workspace,
    duplicate_workspace_book_chapter,
    load_workspace,
    remove_workspace_book_chapter,
    reorder_workspace_book_chapters,
    workspace_payload,
)


def _create(tmp_path: Path):
    return create_book_workspace(
        tmp_path,
        folder_name="کتاب-آزمایشی",
        title="کتاب آزمایشی",
        language="fa-IR",
        direction="rtl",
    )


def test_create_book_workspace_is_offline_safe_and_ready_to_open(tmp_path: Path) -> None:
    workspace = _create(tmp_path)
    root = tmp_path / "کتاب-آزمایشی"
    payload = workspace_payload(workspace)

    assert workspace.root == root.resolve()
    assert payload["ok"] is True
    assert payload["config"] == "mardas.toml"
    assert len(str(payload["config_sha256"])) == 64
    assert payload["book"] == {
        "enabled": True,
        "title": "کتاب آزمایشی",
        "language": "fa-IR",
        "direction": "rtl",
        "output": "dist/book.pdf",
        "output_name": "book.pdf",
        "chapter_count": 1,
        "chapters": [
            {
                "index": 1,
                "path": "chapters/01-introduction.md",
                "title": "مقدمه",
            }
        ],
    }
    assert (root / "chapters/01-introduction.md").read_text(encoding="utf-8") == "# مقدمه\n\n"
    assert (root / "assets").is_dir()
    assert (root / "bibliography").is_dir()
    assert (root / "dist").is_dir()
    config = (root / "mardas.toml").read_text(encoding="utf-8")
    assert 'title = "کتاب آزمایشی"' in config
    assert 'language = "fa-IR"' in config
    assert 'direction = "rtl"' in config
    assert config.count("[book]") == 1


@pytest.mark.parametrize(
    "folder",
    ["../escape", "bad/name", "bad:name", "CON", "trailing.", ".hidden", ".hidden/name"],
)
def test_create_book_workspace_rejects_unsafe_folder_names(
    tmp_path: Path, folder: str
) -> None:
    with pytest.raises(WorkspaceError) as exc_info:
        create_book_workspace(
            tmp_path,
            folder_name=folder,
            title="Unsafe",
            language="en-US",
            direction="ltr",
        )
    assert exc_info.value.code == "invalid_book_folder"


def test_create_book_workspace_rejects_existing_target_and_symlink_parent(
    tmp_path: Path,
) -> None:
    (tmp_path / "existing").mkdir()
    with pytest.raises(WorkspaceError) as exc_info:
        create_book_workspace(
            tmp_path,
            folder_name="existing",
            title="Existing",
            language="en-US",
            direction="ltr",
        )
    assert exc_info.value.code == "book_project_exists"

    link = tmp_path / "parent-link"
    try:
        os.symlink(tmp_path, link)
    except OSError:
        return
    with pytest.raises(WorkspaceError) as link_error:
        create_book_workspace(
            link,
            folder_name="linked",
            title="Linked",
            language="en-US",
            direction="ltr",
        )
    assert link_error.value.code == "blocked_project_symlink"


def test_chapter_lifecycle_preserves_sources_and_detects_stale_config(
    tmp_path: Path,
) -> None:
    workspace = _create(tmp_path)
    original = workspace_payload(workspace)

    workspace, second = add_workspace_book_chapter(
        workspace,
        title="فصل دوم",
        expected_config_sha256=str(original["config_sha256"]),
    )
    second_path = workspace.root / str(second["path"])
    assert second_path.is_file()
    assert second_path.read_text(encoding="utf-8") == "# فصل دوم\n\n"

    after_add = workspace_payload(workspace)
    with pytest.raises(WorkspaceError) as stale:
        add_workspace_book_chapter(
            workspace,
            title="نباید ساخته شود",
            expected_config_sha256=str(original["config_sha256"]),
        )
    assert stale.value.code == "project_config_changed"
    assert not any("نباید" in path.name for path in workspace.root.rglob("*.md"))

    workspace, duplicate = duplicate_workspace_book_chapter(
        workspace,
        relative_path=str(second["path"]),
        title="فصل دوم کپی",
        expected_config_sha256=str(after_add["config_sha256"]),
    )
    duplicate_path = workspace.root / str(duplicate["path"])
    assert duplicate_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")

    payload = workspace_payload(workspace)
    paths = [str(item["path"]) for item in payload["book"]["chapters"]]
    workspace = reorder_workspace_book_chapters(
        workspace,
        ordered_paths=list(reversed(paths)),
        expected_config_sha256=str(payload["config_sha256"]),
    )
    reordered = workspace_payload(workspace)
    assert [item["path"] for item in reordered["book"]["chapters"]] == list(
        reversed(paths)
    )

    removed_source = workspace.root / paths[0]
    workspace = remove_workspace_book_chapter(
        workspace,
        relative_path=paths[0],
        expected_config_sha256=str(reordered["config_sha256"]),
    )
    assert removed_source.is_file(), "Remove from book must never delete the chapter file"
    remaining = workspace_payload(workspace)
    assert paths[0] not in [item["path"] for item in remaining["book"]["chapters"]]


def test_chapter_update_preserves_quoted_toml_sections_after_book(tmp_path: Path) -> None:
    workspace = _create(tmp_path)
    config_path = workspace.root / "mardas.toml"
    original = config_path.read_text(encoding="utf-8")
    book_start = original.index("[book]")
    book_section = original[book_start:].strip()
    before_book = original[:book_start].rstrip()
    output_start = before_book.index("[output]")
    reordered = (
        before_book[:output_start].rstrip()
        + "\n\n"
        + book_section
        + "\n\n"
        + before_book[output_start:].lstrip()
    )
    reordered = reordered.replace("[output]", '["output"]', 1)
    reordered = reordered.replace("[appearance]", "['appearance']", 1)
    config_path.write_text(reordered.rstrip() + "\n", encoding="utf-8")
    workspace = load_workspace(workspace.root)
    payload = workspace_payload(workspace)

    workspace, _chapter = add_workspace_book_chapter(
        workspace,
        title="Preserved sections",
        expected_config_sha256=str(payload["config_sha256"]),
    )

    updated = (workspace.root / "mardas.toml").read_text(encoding="utf-8")
    assert '["output"]' in updated
    assert "['appearance']" in updated
    assert 'page_size = "A4"' in updated
    assert 'style = "modern"' in updated
    assert workspace_payload(workspace)["book"]["chapter_count"] == 2


def test_chapter_reorder_requires_exact_unique_set(tmp_path: Path) -> None:
    workspace = _create(tmp_path)
    payload = workspace_payload(workspace)
    for invalid in ([], ["chapters/missing.md"], ["chapters/01-introduction.md"] * 2):
        with pytest.raises(WorkspaceError) as exc_info:
            reorder_workspace_book_chapters(
                workspace,
                ordered_paths=invalid,
                expected_config_sha256=str(payload["config_sha256"]),
            )
        assert exc_info.value.code == "invalid_book_chapter_order"


def test_last_chapter_cannot_be_removed(tmp_path: Path) -> None:
    workspace = _create(tmp_path)
    payload = workspace_payload(workspace)
    with pytest.raises(WorkspaceError) as exc_info:
        remove_workspace_book_chapter(
            workspace,
            relative_path="chapters/01-introduction.md",
            expected_config_sha256=str(payload["config_sha256"]),
        )
    assert exc_info.value.code == "book_requires_chapter"


def test_engine_service_exposes_complete_book_project_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = EngineService()
    created = service.dispatch(
        "book.create",
        {
            "parent_path": str(tmp_path),
            "folder_name": "service-book",
            "title": "Service Book",
            "language": "en-US",
            "direction": "ltr",
        },
    )
    assert created["book"]["chapter_count"] == 1
    project_path = str(created["path"])

    added = service.dispatch(
        "book.add_chapter",
        {
            "project_path": project_path,
            "title": "Methods",
            "expected_config_sha256": created["config_sha256"],
        },
    )
    assert added["book"]["chapter_count"] == 2

    validation = service.dispatch("book.validate", {"project_path": project_path})
    assert validation["ok"] is True
    assert validation["book"]["chapter_count"] == 2

    preview = service.dispatch("book.preview", {"project_path": project_path})
    assert "Service Book" in preview["html"]
    assert preview["project"]["book"]["chapter_count"] == 2

    output = tmp_path / "exported.pdf"

    def fake_export(workspace, output_path, **_kwargs):
        Path(output_path).write_bytes(b"%PDF-1.7\n%%EOF\n")
        return Path(output_path), "book.pdf", workspace

    monkeypatch.setattr(application, "export_workspace_book_pdf", fake_export)
    exported = service.dispatch(
        "book.export",
        {"project_path": project_path, "output_path": str(output)},
    )
    assert exported["output_path"] == str(output)
    assert exported["size_bytes"] == output.stat().st_size
    service.close()


def test_sidecar_allows_new_book_methods() -> None:
    expected = {
        "book.create",
        "book.add_chapter",
        "book.duplicate_chapter",
        "book.reorder_chapters",
        "book.remove_chapter",
        "book.validate",
        "book.preview",
        "book.export",
    }
    assert expected <= sidecar._HEAVY_METHODS
    methods = set(EngineService().capabilities()["methods"])
    assert expected <= methods


def test_engine_service_rejects_unknown_book_parameters(tmp_path: Path) -> None:
    service = EngineService()
    with pytest.raises(EngineError) as exc_info:
        service.dispatch(
            "book.create",
            {
                "parent_path": str(tmp_path),
                "folder_name": "bad",
                "title": "Bad",
                "unknown": True,
            },
        )
    assert exc_info.value.code == "MARDAS-INVALID-PARAMS"
