from __future__ import annotations

import json
import os
import stat
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

import pytest

from mardas_md2pdf import gui
from mardas_md2pdf.workspace import (
    WorkspaceError,
    load_workspace,
    read_workspace_file,
    search_workspace,
    workspace_bibliography,
    workspace_payload,
    write_workspace_file,
)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    chapters = root / "chapters"
    chapters.mkdir(parents=True)
    (root / "mardas.toml").write_text(
        """schema_version = 1

[project]
title = "Studio Book"
direction = "rtl"

[book]
chapters = ["chapters/01-intro.md", "chapters/02-method.md"]
output = "dist/book.pdf"
chapter_page_break = true

[output]
toc = true

[references]
enabled = true
""",
        encoding="utf-8",
    )
    (chapters / "01-intro.md").write_text("# مقدمه\n\nمتن فصل اول.\n", encoding="utf-8")
    (chapters / "02-method.md").write_text("# Method\n\nSecond chapter.\n", encoding="utf-8")
    (root / "references.bib").write_text(
        "@book{a, title={A}, author={Doe}, year={2025}}\n", encoding="utf-8"
    )
    (root / "dist").mkdir()
    (root / "dist" / "ignored.txt").write_text("generated", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.txt").write_text("dependency", encoding="utf-8")
    (root / "target").mkdir()
    (root / "target" / "ignored.txt").write_text("compiled", encoding="utf-8")
    return root


def _server(workspace):
    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    server.studio_project_workspace = workspace  # type: ignore[attr-defined]
    server.studio_preview_state_lock = Lock()  # type: ignore[attr-defined]
    server.studio_preview_render_lock = Lock()  # type: ignore[attr-defined]
    server.studio_latest_preview_ids = {}  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _headers(server, *, json_content: bool = False):
    headers = {
        "Origin": f"http://127.0.0.1:{server.server_port}",
        "X-Mardas-Studio-Token": "secret",
    }
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def test_workspace_lists_relative_project_files_and_book_chapters(tmp_path):
    root = _project(tmp_path)
    workspace = load_workspace(root)
    payload = workspace_payload(workspace)

    assert payload["enabled"] is True
    assert payload["name"] == "project"
    assert payload["config"] == "mardas.toml"
    assert payload["book"]["chapter_count"] == 2
    files = payload["files"]
    assert [item["path"] for item in files[:2]] == [
        "chapters/01-intro.md",
        "chapters/02-method.md",
    ]
    assert all(not str(item["path"]).startswith(str(root)) for item in files)
    listed = {item["path"] for item in files}
    assert "dist/ignored.txt" not in listed
    assert "node_modules/ignored.txt" not in listed
    assert "target/ignored.txt" not in listed


def test_workspace_file_read_save_and_conflict_detection(tmp_path):
    root = _project(tmp_path)
    workspace = load_workspace(root)
    source = root / "chapters/01-intro.md"
    source.chmod(0o640)
    opened = read_workspace_file(workspace, "chapters/01-intro.md")

    saved = write_workspace_file(
        workspace,
        "chapters/01-intro.md",
        "# مقدمه جدید\n",
        expected_sha256=str(opened["sha256"]),
    )
    assert saved["content"] == "# مقدمه جدید\n"
    assert source.read_text(encoding="utf-8") == "# مقدمه جدید\n"
    if os.name != "nt":
        assert stat.S_IMODE(source.stat().st_mode) == 0o640

    with pytest.raises(WorkspaceError) as exc_info:
        write_workspace_file(
            workspace,
            "chapters/01-intro.md",
            "# stale\n",
            expected_sha256=str(opened["sha256"]),
        )
    assert exc_info.value.status == 409
    assert exc_info.value.code == "project_file_changed"


def test_workspace_rejects_escape_hidden_generated_and_symlink_paths(tmp_path):
    root = _project(tmp_path)
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    link = root / "chapters" / "link.md"
    internal_link = root / "chapters" / "internal-link.md"
    try:
        os.symlink(outside, link)
        os.symlink(root / "chapters/01-intro.md", internal_link)
    except OSError:
        pytest.skip("symlinks are unavailable")
    workspace = load_workspace(root)

    for relative in (
        "../secret.md",
        ".git/config",
        "dist/ignored.txt",
        "chapters/link.md",
        "chapters/internal-link.md",
    ):
        with pytest.raises(WorkspaceError):
            read_workspace_file(workspace, relative)


def test_studio_project_http_contract_loads_reads_and_saves(tmp_path):
    workspace = load_workspace(_project(tmp_path))
    server, thread = _server(workspace)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request("GET", "/api/project", headers=_headers(server))
        response = connection.getresponse()
        project = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert project["enabled"] is True
        assert project["book"]["chapter_count"] == 2

        connection.request(
            "GET",
            "/api/project/file?path=chapters%2F01-intro.md",
            headers=_headers(server),
        )
        response = connection.getresponse()
        file_payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert file_payload["path"] == "chapters/01-intro.md"

        body = json.dumps(
            {
                "path": file_payload["path"],
                "content": "# Saved from Studio\n",
                "expected_sha256": file_payload["sha256"],
            }
        )
        connection.request(
            "POST",
            "/api/project/save",
            body=body,
            headers=_headers(server, json_content=True),
        )
        response = connection.getresponse()
        saved = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert saved["file"]["content"] == "# Saved from Studio\n"
        assert saved["project"]["enabled"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_studio_project_http_requires_token_and_hides_disabled_mode(tmp_path):
    server, thread = _server(None)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request("GET", "/api/project")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 403
        assert payload["code"] == "invalid_studio_token"

        connection.request("GET", "/api/project", headers=_headers(server))
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload == {"enabled": False}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_gui_parser_accepts_explicit_project_workspace(tmp_path):
    root = _project(tmp_path)
    args = gui.build_parser().parse_args(["--project", str(root), "--no-open"])
    assert args.project == root
    assert args.no_open is True


def test_project_renderer_preview_uses_unsaved_markdown_and_project_assets(tmp_path):
    root = _project(tmp_path)
    assets = root / "assets"
    assets.mkdir()
    (assets / "mark.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20"/></svg>',
        encoding="utf-8",
    )
    workspace = load_workspace(root)
    server, thread = _server(workspace)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        body = json.dumps(
            {
                "path": "chapters/01-intro.md",
                "content": "# Unsaved preview\n\n![Mark](../assets/mark.svg)\n",
            }
        )
        headers = _headers(server, json_content=True)
        headers["X-Mardas-Studio-Preview-Id"] = "project-preview-1"
        headers["X-Mardas-Studio-Client-Id"] = "project-client"
        connection.request(
            "POST",
            "/api/project/render-file-html",
            body=body,
            headers=headers,
        )
        response = connection.getresponse()
        html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 200
    assert "Unsaved preview" in html
    assert "data:image/svg+xml;base64," in html
    assert 'id="mardas-studio-preview-css"' in html
    assert str(root) not in html


def test_project_validation_api_returns_relative_diagnostic_locations(tmp_path):
    root = _project(tmp_path)
    (root / "chapters/02-method.md").write_text("# Method\n\nSee @fig:missing.\n", encoding="utf-8")
    workspace = load_workspace(root)
    server, thread = _server(workspace)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request(
            "POST",
            "/api/project/validate",
            body="{}",
            headers=_headers(server, json_content=True),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 200
    assert payload["ok"] is False
    unresolved = next(item for item in payload["diagnostics"] if item["code"] == "MARDAS-E602")
    assert unresolved["path"] == "chapters/02-method.md"
    assert all(
        not str(item.get("path", "")).startswith(str(root)) for item in payload["diagnostics"]
    )


def test_project_book_html_api_renders_saved_project_without_path_leakage(tmp_path):
    root = _project(tmp_path)
    workspace = load_workspace(root)
    server, thread = _server(workspace)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=20)
        headers = _headers(server, json_content=True)
        headers["X-Mardas-Studio-Preview-Id"] = "book-preview-1"
        headers["X-Mardas-Studio-Client-Id"] = "project-client"
        connection.request(
            "POST",
            "/api/project/render-book-html",
            body="{}",
            headers=headers,
        )
        response = connection.getresponse()
        html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 200
    assert "Studio Book" in html
    assert "Method" in html
    assert 'id="mardas-studio-preview-css"' in html
    assert str(root) not in html


def test_book_diagnostics_keep_citation_chapter_path(tmp_path):
    root = _project(tmp_path)
    config_path = root / "mardas.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[bibliography]\nenabled = true\nsources = [\"references.bib\"]\n",
        encoding="utf-8",
    )
    (root / "chapters/02-method.md").write_text(
        "# Method\n\nMissing citation [@missing2025].\n",
        encoding="utf-8",
    )

    payload = workspace_payload(load_workspace(root))
    missing = next(item for item in payload["diagnostics"] if item["code"] == "MARDAS-E704")
    assert missing["path"] == "chapters/02-method.md"
    assert not str(missing["path"]).startswith(str(root))


def test_project_save_api_rejects_external_changes_without_overwriting(tmp_path):
    root = _project(tmp_path)
    workspace = load_workspace(root)
    server, thread = _server(workspace)
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request(
            "GET",
            "/api/project/file?path=chapters%2F01-intro.md",
            headers=_headers(server),
        )
        response = connection.getresponse()
        opened = json.loads(response.read().decode("utf-8"))
        source = root / "chapters/01-intro.md"
        source.write_text("# External change\n", encoding="utf-8")

        body = json.dumps(
            {
                "path": opened["path"],
                "content": "# Stale Studio content\n",
                "expected_sha256": opened["sha256"],
            }
        )
        connection.request(
            "POST",
            "/api/project/save",
            body=body,
            headers=_headers(server, json_content=True),
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 409
    assert payload["code"] == "project_file_changed"
    assert source.read_text(encoding="utf-8") == "# External change\n"


def test_workspace_rejects_invalid_encoding_and_oversized_text(tmp_path, monkeypatch):
    root = _project(tmp_path)
    invalid = root / "invalid.txt"
    invalid.write_bytes(b"\xff\xfe\x00")
    large = root / "large.txt"
    large.write_bytes(b"x" * 33)
    workspace = load_workspace(root)

    with pytest.raises(WorkspaceError) as invalid_exc:
        read_workspace_file(workspace, "invalid.txt")
    assert invalid_exc.value.code == "invalid_project_file_encoding"

    monkeypatch.setattr("mardas_md2pdf.workspace.MAX_WORKSPACE_TEXT_BYTES", 32)
    with pytest.raises(WorkspaceError) as large_exc:
        read_workspace_file(workspace, "large.txt")
    assert large_exc.value.code == "project_file_too_large"
    assert large_exc.value.status == 413


def test_visual_audit_script_supports_project_mode():
    script = (Path(__file__).resolve().parents[1] / "scripts/audit_studio_visual.py").read_text(
        encoding="utf-8"
    )
    assert '"--project"' in script
    assert 'page.route("**/api/**", proxy_studio_api)' in script
    assert '"project_section_visible"' in script
    assert '"project_file_count"' in script


def test_studio_html_contains_project_explorer_problems_and_book_actions():
    html = (Path(__file__).resolve().parents[1] / "src/mardas_md2pdf/assets/gui.html").read_text(
        encoding="utf-8"
    )

    assert 'id="projectWorkspaceSection"' in html
    assert 'id="projectFileTree"' in html
    assert 'id="problemsSection"' in html
    assert 'id="problemList"' in html
    assert "function loadServerProject" in html
    assert "function saveServerProjectFile" in html
    assert "function validateServerProject" in html
    assert "function previewServerBook" in html
    assert 'id="cancelExportBtn"' in html
    assert "function runQueuedExport" in html
    assert "function cancelActiveExport" in html
    assert "function exportServerBook" in html
    assert "/api/project/render-file-html" in html
    assert "/api/project/render-book-html" in html
    assert "gotoEditorLine" in html


def test_workspace_search_is_bounded_unicode_aware_and_cancellable(tmp_path):
    root = _project(tmp_path)
    (root / "notes.txt").write_text("سلام دنیا\nNeural network\nسلام دوباره\n", encoding="utf-8")
    workspace = load_workspace(root)

    literal = search_workspace(workspace, "سلام")
    assert literal["searched_files"] >= 3
    assert [(item["path"], item["line"]) for item in literal["matches"]] == [
        ("notes.txt", 1),
        ("notes.txt", 3),
    ]

    regex = search_workspace(workspace, r"Neural\s+network", regex=True)
    assert regex["matches"][0]["path"] == "notes.txt"
    assert regex["matches"][0]["column"] == 1

    bounded = search_workspace(workspace, "سلام", max_results=1)
    assert len(bounded["matches"]) == 1
    assert bounded["truncated"] is True

    for unsafe_query in (
        r"(a+)+$",
        r"(a|aa)+$",
        r"(a(a|aa)){1000}b",
        r"a{1,1001}",
        r"a*a*a*a*a*a*a*a*a*a*b",
    ):
        with pytest.raises(WorkspaceError) as unsafe:
            search_workspace(workspace, unsafe_query, regex=True)
        assert unsafe.value.code == "unsafe_project_search_regex"

    escaped_quantifiers = search_workspace(workspace, r"\*\+\?", regex=True)
    assert escaped_quantifiers["matches"] == []

    with pytest.raises(WorkspaceError) as cancelled:
        search_workspace(workspace, "سلام", cancelled=lambda: True)
    assert cancelled.value.status == 499


def test_workspace_bibliography_indexes_searches_and_marks_cited_entries(tmp_path):
    root = _project(tmp_path)
    config = root / "mardas.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + '\n[bibliography]\nenabled = true\nsources = ["references.bib"]\n',
        encoding="utf-8",
    )
    workspace = load_workspace(root)
    result = workspace_bibliography(
        workspace,
        query="doe",
        cited_keys=("a",),
    )

    assert result["ok"] is True
    assert result["entry_count"] == 1
    assert result["sources"] == ["references.bib"]
    assert result["entries"][0]["key"] == "a"
    assert result["entries"][0]["cited"] is True
    assert result["entries"][0]["source_path"] == "references.bib"
