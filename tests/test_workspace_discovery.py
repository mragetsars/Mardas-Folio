from __future__ import annotations

from pathlib import Path

import pytest

from mardas_folio import application, workspace
from mardas_folio.renderer import RenderCancelledError


def test_asset_discovery_prunes_generated_hidden_deep_and_symlink_directories(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    document.write_text("# Report", encoding="utf-8")
    for directory in ["assets", ".hidden", "node_modules", ".venv", "a/b/c/d"]:
        folder = tmp_path / directory
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "image.png").write_bytes(b"png")
    try:
        (tmp_path / "linked-assets").symlink_to(tmp_path / "assets", target_is_directory=True)
    except OSError:
        pass
    result = application.list_document_assets(document)
    assert [item["relative_path"] for item in result["assets"]] == ["assets/image.png"]


def test_asset_discovery_stops_at_result_and_scan_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ["a.png", "b.png", "c.png", "d.png"]:
        (tmp_path / name).write_bytes(b"png")
    monkeypatch.setattr(application, "MAX_DOCUMENT_ASSETS", 2)
    result = application.list_document_assets(tmp_path / "report.md")
    assert [item["name"] for item in result["assets"]] == ["a.png", "b.png"]
    assert result["truncated"] is True
    monkeypatch.setattr(application, "MAX_DOCUMENT_ASSETS", 500)
    monkeypatch.setattr(application, "MAX_DOCUMENT_ASSET_SCAN_ENTRIES", 1)
    result = application.list_document_assets(tmp_path / "report.md")
    assert len(result["assets"]) == 1
    assert result["truncated"] is True


def test_asset_discovery_honors_sidecar_cancellation(tmp_path: Path) -> None:
    with pytest.raises(RenderCancelledError):
        application.EngineService().dispatch(
            "document.list_assets",
            {"path": str(tmp_path / "report.md")},
            cancelled=lambda: True,
        )


def test_workspace_file_limit_stops_consuming_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [tmp_path / "a.md", tmp_path / "b.md", tmp_path / "c.md"]
    for path in files:
        path.write_text("# Report", encoding="utf-8")

    def bounded_tree(root, *, cancelled=None):
        yield from files
        raise AssertionError("Discovery scanned past its output limit")

    monkeypatch.setattr(workspace, "MAX_WORKSPACE_FILES", 2)
    monkeypatch.setattr(workspace, "_iter_workspace_files", bounded_tree)
    found, diagnostics = workspace._workspace_files(tmp_path, None)
    assert [item.path for item in found] == ["a.md", "b.md"]
    assert diagnostics[0].code == "MARDAS-W801"


def _book(tmp_path: Path) -> Path:
    (tmp_path / "mardas.toml").write_text(
        'schema_version = 1\n[book]\nchapters = ["first.md", "second.md"]\n',
        encoding="utf-8",
    )
    (tmp_path / "first.md").write_text("# First\n", encoding="utf-8")
    (tmp_path / "second.md").write_text("# Second\n", encoding="utf-8")
    return tmp_path


def test_project_file_operations_do_not_parse_entire_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _book(tmp_path)

    def unexpected_render(*args, **kwargs):
        raise AssertionError("File operations must not render book contents")

    monkeypatch.setattr(workspace, "validate_book_project", unexpected_render)
    monkeypatch.setattr(workspace, "render_book", unexpected_render)
    service = application.EngineService()
    opened = service.dispatch(
        "project.read", {"project_path": str(tmp_path), "relative_path": "first.md"}
    )
    assert opened["content"] == "# First\n"
    saved = service.dispatch(
        "project.save",
        {
            "project_path": str(tmp_path),
            "relative_path": "first.md",
            "content": "# Updated\n",
            "expected_sha256": opened["sha256"],
        },
    )
    assert saved["content"] == "# Updated\n"
    result = service.dispatch("project.search", {"project_path": str(tmp_path), "query": "Updated"})
    assert result["matches"][0]["path"] == "first.md"
    service.dispatch("bibliography.index", {"project_path": str(tmp_path)})


@pytest.mark.parametrize("method", ["book.validate", "book.preview"])
def test_book_operations_validate_contents_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    _book(tmp_path)
    validate = workspace.validate_book_project
    calls = 0

    def record_validation(*args, **kwargs):
        nonlocal calls
        calls += 1
        return validate(*args, **kwargs)

    monkeypatch.setattr(workspace, "validate_book_project", record_validation)
    application.EngineService().dispatch(method, {"project_path": str(tmp_path)})
    assert calls == 1


def test_workspace_discovery_honors_cancellation(tmp_path: Path) -> None:
    _book(tmp_path)
    with pytest.raises(RenderCancelledError):
        workspace.load_workspace(tmp_path, cancelled=lambda: True, validate_content=False)
