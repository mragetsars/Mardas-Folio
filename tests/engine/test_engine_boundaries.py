"""Public application behavior across the extracted file and request services."""

import ast
import json
import os
import subprocess
import sys

import pytest

from mardas_folio.application import EngineError
from tests._paths import ROOT


@pytest.mark.parametrize("extension,method", [("md", "document"), ("txt", "text")])
@pytest.mark.parametrize("bom,crlf", [(False, False), (True, True)])
def test_read_edit_conflict_lifecycle(
    engine_service, document_factory, extension, method, bom, crlf
):
    path = document_factory(f"اسناد/report.{extension}", "# سلام\nEnglish\n", bom=bom, crlf=crlf)
    read = "document.read" if method == "document" else "document.read_text"
    save = "document.save" if method == "document" else "document.save_text"
    opened = engine_service.dispatch(read, {"path": str(path)})
    saved = engine_service.dispatch(
        save,
        {
            "path": str(path),
            "content": "# سلام\nEdited\n",
            "expected_revision": opened["revision"],
        },
    )
    assert saved["revision"] != opened["revision"]
    expected = "# سلام\r\nEdited\r\n" if crlf else "# سلام\nEdited\n"
    assert path.read_bytes() == (b"\xef\xbb\xbf" if bom else b"") + expected.encode()
    with pytest.raises(EngineError) as caught:
        engine_service.dispatch(
            save,
            {
                "path": str(path),
                "content": "stale",
                "expected_revision": opened["revision"],
            },
        )
    assert caught.value.code == "MARDAS-DOCUMENT-CONFLICT"


@pytest.mark.parametrize(
    "method,params",
    [
        ("document.save", {"path": "a.md", "content": "x", "force": "yes"}),
        ("document.read", {"path": "a.md", "unknown": True}),
        ("document.read", {"path": "a\u0000.md"}),
        ("document.read", {"path": "\ud800"}),
    ],
)
def test_invalid_requests_fail_before_filesystem_work(engine_service, method, params):
    with pytest.raises(EngineError) as caught:
        engine_service.dispatch(method, params)
    assert caught.value.code == "MARDAS-INVALID-PARAMS"


@pytest.mark.parametrize(
    "module",
    [
        "file_io",
        "document_store",
        "engine_errors",
        "request_validation",
        "render_contracts",
        "page_geometry",
        "print_layout",
        "render_requests",
    ],
)
def test_leaf_services_do_not_depend_on_rendering_or_transport(module):
    root = ROOT / "src" / "mardas_folio"
    tree = ast.parse((root / f"{module}.py").read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1
    }
    assert not imports.intersection({"application", "sidecar", "gui", "renderer", "workspace"})


@pytest.mark.parametrize("module", ["config", "render_requests"])
def test_configuration_does_not_load_document_parsers_or_browser_runtime(module):
    root = ROOT
    code = (
        "import importlib, json, sys; "
        f"importlib.import_module('mardas_folio.{module}'); "
        "print(json.dumps(sorted(sys.modules)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    loaded = set(json.loads(result.stdout))
    assert not loaded.intersection(
        {
            "mardas_folio.renderer",
            "mardas_folio.markdown",
            "playwright",
            "pypdf",
            "bs4",
        }
    )


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("markup", {"markdown", "renderer", "workspace", "application", "sidecar"}),
        ("publishing", {"renderer", "workspace", "application", "sidecar"}),
        ("projects", {"workspace", "project_commands", "cli", "application", "sidecar"}),
    ],
)
def test_implementation_packages_do_not_import_their_facades(package, forbidden):
    """A facade may re-export its implementation; the reverse creates a cycle."""
    from importlib.util import resolve_name

    for path in (ROOT / "src" / "mardas_folio" / package).glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                name = "." * node.level + (node.module or "")
                module = resolve_name(name, f"mardas_folio.{package}") if node.level else name
                assert module not in {f"mardas_folio.{name}" for name in forbidden}, path
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in {f"mardas_folio.{name}" for name in forbidden}, path
