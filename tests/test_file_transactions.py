from __future__ import annotations

import hashlib
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from mardas_folio import application, config, markdown, renderer, workspace


def _book(tmp_path: Path) -> workspace.ProjectWorkspace:
    return workspace.create_book_workspace(
        tmp_path, folder_name="book", title="Original", language="en-US"
    )


def test_book_payload_revision_belongs_to_the_parsed_configuration(tmp_path: Path) -> None:
    project = _book(tmp_path)
    path = project.root / "mardas.toml"
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    external = path.read_text(encoding="utf-8").replace('title = "Original"', 'title = "External"')
    path.write_text(external, encoding="utf-8")

    payload = workspace.workspace_payload(project)
    assert payload["book"]["title"] == "Original"
    assert payload["config_sha256"] == original_hash
    # A client supplying a current hash cannot make an old manifest current.
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.add_workspace_book_chapter(
            project,
            title="Stale chapter",
            expected_config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    assert error.value.code == "project_config_changed"
    assert path.read_text(encoding="utf-8") == external
    assert len(list((project.root / "chapters").glob("*.md"))) == 1


def test_config_revision_uses_the_same_bytes_as_the_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mardas.toml"
    original = b'\xef\xbb\xbfschema_version = 1\n[project]\ntitle = "Original"\n'
    path.write_bytes(original)
    parse = config.tomllib.loads

    def change_after_read(text: str):
        path.write_text('schema_version = 1\n[project]\ntitle = "External"\n', encoding="utf-8")
        return parse(text)

    monkeypatch.setattr(config.tomllib, "loads", change_after_read)
    loaded = config.load_project_config(start=tmp_path)
    assert loaded.config.values["title"] == "Original"
    assert loaded.config.source_sha256 == hashlib.sha256(original).hexdigest()
    assert loaded.config.source_sha256 != hashlib.sha256(path.read_bytes()).hexdigest()


def test_book_edit_rechecks_config_after_writing_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _book(tmp_path)
    path = project.root / "mardas.toml"
    payload = workspace.workspace_payload(project)
    external = path.read_text(encoding="utf-8").replace('title = "Original"', 'title = "External"')
    fsync = workspace.os.fsync

    def edit_after_flush(descriptor: int) -> None:
        fsync(descriptor)
        path.write_text(external, encoding="utf-8")

    monkeypatch.setattr(workspace.os, "fsync", edit_after_flush)
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.reorder_workspace_book_chapters(
            project,
            ordered_paths=["chapters/01-introduction.md"],
            expected_config_sha256=str(payload["config_sha256"]),
        )
    assert error.value.code == "project_config_changed"
    assert path.read_text(encoding="utf-8") == external
    assert not list(project.root.glob(".mardas.toml.*"))


def test_concurrent_chapter_additions_cannot_delete_the_winning_chapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _book(tmp_path)
    revision = str(workspace.workspace_payload(project)["config_sha256"])
    first_written, release_first, second_done = Event(), Event(), Event()
    write = workspace._atomic_replace_text

    def pause_first(path: Path, content: str, **kwargs):
        write(path, content, **kwargs)
        if content == "# First writer\n":
            first_written.set()
            assert release_first.wait(5)

    monkeypatch.setattr(workspace, "_atomic_replace_text", pause_first)

    def add(body: str):
        try:
            return workspace.add_workspace_book_chapter(
                project, title="Same title", content=body, expected_config_sha256=revision
            )
        except workspace.WorkspaceError as error:
            return error.code
        finally:
            if body == "# Second writer\n":
                second_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(add, "# First writer\n")
        assert first_written.wait(5)
        second = executor.submit(add, "# Second writer\n")
        # Before the fix, the second operation overwrote and committed the
        # same filename, then the first operation's rollback deleted it.
        second_done.wait(0.2)
        release_first.set()
        results = [first.result(timeout=5), second.result(timeout=5)]
    assert sum(isinstance(result, tuple) for result in results) == 1
    assert "project_config_changed" in results
    updated = workspace.load_workspace(project.root)
    assert len(updated.manifest.chapters) == 2
    new_path = updated.manifest.chapters[1].path
    assert new_path.read_text(encoding="utf-8") == "# First writer\n"


def test_concurrent_same_named_asset_imports_keep_both_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "document.md"
    first_source = tmp_path / "first" / "image.png"
    second_source = tmp_path / "second" / "image.png"
    for source, content in [(first_source, b"first image"), (second_source, b"second image")]:
        source.parent.mkdir()
        source.write_bytes(content)
    first_started, release_first, second_done = Event(), Event(), Event()
    write = application._atomic_write_bytes

    def pause_first(path: Path, content: bytes):
        if content == b"first image":
            first_started.set()
            assert release_first.wait(5)
        write(path, content)

    monkeypatch.setattr(application, "_atomic_write_bytes", pause_first)

    def import_second():
        try:
            return application.import_document_asset(document, second_source)
        finally:
            second_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(application.import_document_asset, document, first_source)
        assert first_started.wait(5)
        second = executor.submit(import_second)
        second_done.wait(0.2)
        release_first.set()
        imported = [first.result(timeout=5), second.result(timeout=5)]
    assert imported[0]["path"] != imported[1]["path"]
    assert Path(imported[0]["path"]).read_bytes() == b"first image"
    assert Path(imported[1]["path"]).read_bytes() == b"second image"


def test_import_rejects_an_asset_that_grows_after_the_size_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"small")
    original_open = Path.open

    def grow_before_read(path: Path, mode="r", *args, **kwargs):
        if path == source and mode == "rb":
            with original_open(source, "wb") as writer:
                writer.write(b"x" * 33)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(application, "MAX_IMPORTED_ASSET_BYTES", 32)
    monkeypatch.setattr(Path, "open", grow_before_read)
    with pytest.raises(application.EngineError) as error:
        application.import_document_asset(tmp_path / "document.md", source)
    assert error.value.code == "MARDAS-ASSET-TOO-LARGE"
    assert not (tmp_path / "assets").exists()


def test_quality_report_cannot_overwrite_a_bibliography_source(tmp_path: Path) -> None:
    document = tmp_path / "document.md"
    document.write_text("# Document\n", encoding="utf-8")
    bibliography = tmp_path / "references.bib"
    original = "@book{source, title={Preserve me}}\n"
    bibliography.write_text(original, encoding="utf-8")
    options = renderer.PdfOptions(
        input_path=document,
        output_path=tmp_path / "document.pdf",
        quality_report=bibliography,
        bibliography_sources=(bibliography,),
    )
    with pytest.raises(renderer.OutputPathError, match="bibliography source and quality report"):
        renderer._validate_conversion_paths(options)
    assert bibliography.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("quote", ['"""', "'''"])
def test_chapter_edit_preserves_table_like_text_in_multiline_strings(
    tmp_path: Path, quote: str
) -> None:
    project = _book(tmp_path)
    path = project.root / "mardas.toml"
    description = "Example syntax:\n[book]\nchapters = ['example.md']\n[output]\n"
    original = path.read_text(encoding="utf-8").replace(
        'title = "Original"', f'title = "Original"\ndescription = {quote}{description}{quote}'
    )
    path.write_text(original, encoding="utf-8")
    project = workspace.load_workspace(project.root)
    updated, _chapter = workspace.add_workspace_book_chapter(
        project,
        title="New chapter",
        expected_config_sha256=str(workspace.workspace_payload(project)["config_sha256"]),
    )
    assert updated.config.values["description"] == description
    assert len(updated.manifest.chapters) == 2
    assert updated.bundle is not None


@pytest.mark.parametrize(
    "book_settings",
    [
        'book = { chapters = ["chapters/01-introduction.md"] }\n',
        'book.chapters = ["chapters/01-introduction.md"]\n',
    ],
)
def test_unsupported_book_layout_is_rejected_without_corrupting_config(
    tmp_path: Path, book_settings: str
) -> None:
    project = _book(tmp_path)
    path = project.root / "mardas.toml"
    original = "schema_version = 1\n" + book_settings
    path.write_text(original, encoding="utf-8")
    project = workspace.load_workspace(project.root)
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.add_workspace_book_chapter(
            project,
            title="New chapter",
            expected_config_sha256=str(workspace.workspace_payload(project)["config_sha256"]),
        )
    assert error.value.code == "project_config_edit_unsupported"
    assert path.read_text(encoding="utf-8") == original
    assert len(list((project.root / "chapters").glob("*.md"))) == 1


def test_failed_post_commit_refresh_keeps_the_committed_chapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _book(tmp_path)
    revision = str(workspace.workspace_payload(project)["config_sha256"])

    def unavailable_after_commit(*args, **kwargs):
        raise workspace.WorkspaceError("Project was moved externally", code="project_unavailable")

    monkeypatch.setattr(workspace, "load_workspace", unavailable_after_commit)
    with pytest.raises(workspace.WorkspaceError, match="moved externally"):
        workspace.add_workspace_book_chapter(
            project, title="Committed chapter", content="Keep me\n", expected_config_sha256=revision
        )
    config_text = (project.root / "mardas.toml").read_text(encoding="utf-8")
    entries = config.tomllib.loads(config_text)["book"]["chapters"]
    added = project.root / entries[-1]["path"]
    assert added.read_text(encoding="utf-8") == "Keep me\n"


@pytest.mark.parametrize("body", ["", "    indented code\n\n", "\n# Heading\n\n"])
def test_book_add_api_preserves_supplied_content_verbatim(tmp_path: Path, body: str) -> None:
    project = _book(tmp_path)
    service = application.EngineService()
    try:
        response = service.dispatch(
            "book.add_chapter",
            {
                "project_path": str(project.root),
                "title": "New chapter",
                "content": body,
                "expected_config_sha256": workspace.workspace_payload(project)["config_sha256"],
            },
        )
    finally:
        service.close()
    assert Path(response["created_chapter"]["absolute_path"]).read_text(encoding="utf-8") == body


@pytest.mark.parametrize("field", ["title", "content"])
def test_book_add_rejects_non_utf8_input_without_creating_a_file(
    tmp_path: Path, field: str
) -> None:
    project = _book(tmp_path)
    request = {
        "title": "New chapter",
        "content": "Valid content",
        "expected_config_sha256": workspace.workspace_payload(project)["config_sha256"],
    }
    request[field] = "\ud800"
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.add_workspace_book_chapter(project, **request)
    assert error.value.code == ("invalid_book_chapter_title" if field == "title" else "invalid_book_chapter_content")
    assert len(list((project.root / "chapters").glob("*.md"))) == 1


def test_repeated_local_images_are_read_once_per_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"image bytes")
    convert = markdown._image_file_to_data_uri
    reads: list[Path] = []

    def track_read(path: Path):
        reads.append(path)
        return convert(path)

    monkeypatch.setattr(markdown, "_image_file_to_data_uri", track_read)
    html = markdown.embed_local_images(
        '<img src="image.png"><img src="image.png"><img src="./image.png">', tmp_path
    )
    assert html.count("data:image/png;base64,") == 3
    assert reads == [image]


def test_image_embedding_handles_file_growth_without_unbounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"small")
    original_open = Path.open

    def grow_before_read(path: Path, mode="r", *args, **kwargs):
        if path == image and mode == "rb":
            with original_open(image, "wb") as writer:
                writer.write(b"x" * 33)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(markdown, "MAX_EMBED_IMAGE_BYTES", 32)
    monkeypatch.setattr(Path, "open", grow_before_read)
    with pytest.warns(RuntimeWarning, match="larger than 32 bytes"):
        html = markdown.embed_local_images('<img src="image.png">', tmp_path)
    assert 'data-md2pdf-blocked-reason="local"' in html
    assert "eHh4" not in html


def test_image_disappearing_during_read_does_not_break_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"image bytes")
    original_open = Path.open

    def remove_before_read(path: Path, mode="r", *args, **kwargs):
        if path == image and mode == "rb":
            path.unlink()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", remove_before_read)
    with pytest.warns(RuntimeWarning, match="could not be read"):
        html = markdown.embed_local_images('<img src="image.png">', tmp_path)
    assert 'data-md2pdf-blocked-reason="local"' in html


@pytest.mark.parametrize("path", ["invalid\x00.md", "invalid\ud800.md"])
def test_document_api_rejects_invalid_path_text_as_invalid_params(path: str) -> None:
    service = application.EngineService()
    try:
        with pytest.raises(application.EngineError) as error:
            service.dispatch("document.read", {"path": path})
        assert error.value.code == "MARDAS-INVALID-PARAMS"
        assert error.value.details == {"parameter": "path"}
    finally:
        service.close()


@pytest.mark.parametrize("writer", ["document", "asset", "project", "renderer"])
def test_atomic_writers_never_change_the_process_umask(
    tmp_path: Path, writer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "output.txt"
    write = {
        "document": lambda: application._atomic_write_text(target, "new content"),
        "asset": lambda: application._atomic_write_bytes(target, b"new content"),
        "project": lambda: workspace._atomic_replace_text(target, "new content"),
        "renderer": lambda: renderer._atomic_write_text(target, "new content"),
    }[writer]

    def forbid_umask(*args):
        raise AssertionError("Atomic writers must not modify the process-global umask")

    monkeypatch.setattr(os, "umask", forbid_umask)
    write()
    assert target.read_text(encoding="utf-8") == "new content"
    if os.name != "nt":
        target.chmod(0o640)
        write()
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert sorted(tmp_path.iterdir()) == [target]


def test_literal_project_search_finds_text_after_a_long_paragraph_prefix(tmp_path: Path) -> None:
    (tmp_path / "mardas.toml").write_text("schema_version = 1\n", encoding="utf-8")
    prefix = "متن بلند " * 500
    (tmp_path / "document.md").write_text(prefix + "TARGET" + " ادامه" * 200, encoding="utf-8")
    project = workspace.load_workspace(tmp_path)
    result = workspace.search_workspace(project, "TARGET", max_results=1)
    assert result["truncated"] is False
    assert result["truncated_lines"] == 0
    assert result["matches"][0]["column"] == len(prefix) + 1
    assert "TARGET" in result["matches"][0]["preview"]
    assert len(result["matches"][0]["preview"]) <= 302


def test_regex_project_search_reports_its_long_line_limit(tmp_path: Path) -> None:
    (tmp_path / "mardas.toml").write_text("schema_version = 1\n", encoding="utf-8")
    (tmp_path / "document.md").write_text("a" * 3000 + "TARGET", encoding="utf-8")
    project = workspace.load_workspace(tmp_path)
    result = workspace.search_workspace(project, "TARGET", regex=True)
    assert result["matches"] == []
    assert result["truncated_lines"] == 1
    assert result["regex_line_limit"] == 2000


def test_deeply_nested_toml_returns_a_configuration_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "mardas.toml"
    path.write_text("value = " + "[" * 10000 + "]" * 10000, encoding="utf-8")
    result = config.load_project_config(start=tmp_path)
    assert [item.code for item in result.diagnostics] == ["MARDAS-E103"]
    assert result.config.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_asset_import_has_a_stable_user_error(tmp_path: Path) -> None:
    with pytest.raises(application.EngineError) as error:
        application.import_document_asset(tmp_path / "document.md", tmp_path / "missing.png")
    assert error.value.code == "MARDAS-ASSET-INVALID"
    assert not (tmp_path / "assets").exists()


def test_import_does_not_replace_an_existing_file_named_assets(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.write_text("Keep this file", encoding="utf-8")
    source = tmp_path / "image.png"
    source.write_bytes(b"image bytes")
    with pytest.raises(application.EngineError) as error:
        application.import_document_asset(tmp_path / "document.md", source)
    assert error.value.code == "MARDAS-ASSET-INVALID"
    assert assets.read_text(encoding="utf-8") == "Keep this file"
