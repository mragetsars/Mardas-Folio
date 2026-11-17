from __future__ import annotations

from pathlib import Path

import pytest

from mardas_folio.application import EngineError, EngineService


def test_resolve_local_markdown_link_decodes_unicode_and_fragment(tmp_path: Path) -> None:
    root = tmp_path / "کتاب"
    root.mkdir()
    source = root / "بخش اول.md"
    target = root / "بخش دوم ویرایش.md"
    source.write_text("# اول\n", encoding="utf-8")
    target.write_text("# مقصد\n", encoding="utf-8")

    result = EngineService().dispatch(
        "document.resolve_markdown_link",
        {
            "document_path": str(source),
            "href": "%D8%A8%D8%AE%D8%B4%20%D8%AF%D9%88%D9%85%20%D9%88%DB%8C%D8%B1%D8%A7%DB%8C%D8%B4.md#%D9%85%D9%82%D8%B5%D8%AF",
        },
    )
    assert result == {
        "path": str(target.resolve()),
        "relative_path": None,
        "fragment": "مقصد",
    }


def test_resolve_markdown_link_rejects_external_missing_and_outside_paths(tmp_path: Path) -> None:
    source = tmp_path / "current.md"
    source.write_text("# Current\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    service = EngineService()

    for href, code in (
        ("https://example.com/other.md", "MARDAS-LINK-UNSUPPORTED"),
        ("missing.md", "MARDAS-LINK-NOT-FOUND"),
        ("../outside.md", "MARDAS-LINK-OUTSIDE-ROOT"),
        ("C:/private.md", "MARDAS-LINK-UNSUPPORTED"),
        ("image.png", "MARDAS-LINK-UNSUPPORTED"),
    ):
        with pytest.raises(EngineError) as caught:
            service.dispatch(
                "document.resolve_markdown_link",
                {"document_path": str(source), "href": href},
            )
        assert caught.value.code == code


def test_resolve_project_link_requires_a_discovered_markdown_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "chapters").mkdir(parents=True)
    (root / "mardas.toml").write_text(
        'schema_version = 1\n[project]\ntitle = "Link project"\n', encoding="utf-8"
    )
    source = root / "chapters" / "one.md"
    target = root / "chapters" / "two.md"
    outside = tmp_path / "outside.md"
    source.write_text("# One\n", encoding="utf-8")
    target.write_text("# Two\n", encoding="utf-8")
    outside.write_text("# Outside\n", encoding="utf-8")
    result = EngineService().dispatch(
        "document.resolve_markdown_link",
        {
            "document_path": str(source),
            "href": "two.md#two",
            "project_path": str(root),
        },
    )
    assert result["path"] == str(target.resolve())
    assert result["relative_path"] == "chapters/two.md"
    assert result["fragment"] == "two"

    with pytest.raises(EngineError) as caught:
        EngineService().dispatch(
            "document.resolve_markdown_link",
            {
                "document_path": str(source),
                "href": "../../outside.md",
                "project_path": str(root),
            },
        )
    assert caught.value.code == "MARDAS-LINK-OUTSIDE-ROOT"


def test_link_resolution_is_advertised_as_an_additive_capability() -> None:
    assert "document.resolve_markdown_link" in EngineService().capabilities()["methods"]
