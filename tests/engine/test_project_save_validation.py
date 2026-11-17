from __future__ import annotations

from pathlib import Path

import pytest

from mardas_folio import application


@pytest.mark.parametrize(
    ("filename", "original", "invalid"),
    [
        ("mardas.toml", "schema_version = 1\n", "[project\ninvalid"),
        ("references.bib", "@article{good, title={Good}}\n", "@article{broken, title={"),
        ("references.json", '[{"id":"good","title":"Good"}]\n', '{"items": ['),
    ],
)
def test_project_save_preserves_invalid_managed_files(
    tmp_path: Path,
    filename: str,
    original: str,
    invalid: str,
) -> None:
    config = tmp_path / "mardas.toml"
    config.write_text("schema_version = 1\n", encoding="utf-8")
    if filename.endswith(".json"):
        config.write_text(
            'schema_version = 1\n[bibliography]\nenabled = true\nsources = ["references.json"]\n',
            encoding="utf-8",
        )
    target = tmp_path / filename
    if filename != "mardas.toml":
        target.write_text(original, encoding="utf-8")
    before = target.read_bytes()
    service = application.EngineService()
    read = service.dispatch(
        "project.read", {"project_path": str(tmp_path), "relative_path": filename}
    )
    with pytest.raises(application.EngineError):
        service.dispatch(
            "project.save",
            {
                "project_path": str(tmp_path),
                "relative_path": filename,
                "content": invalid,
                "expected_sha256": read["sha256"],
            },
        )
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(f".{target.stem}.*{target.suffix}"))


def test_project_save_rejects_invalid_utf8_before_cancellable_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_load(*args, **kwargs):
        raise AssertionError("invalid request content must be rejected before project discovery")

    monkeypatch.setattr(application, "_load_workspace_request", unexpected_load)
    with pytest.raises(application.EngineError) as caught:
        application.EngineService().dispatch(
            "project.save",
            {
                "project_path": "/project",
                "relative_path": "chapter.md",
                "content": "\ud800",
                "expected_sha256": "revision",
            },
            cancelled=lambda: True,
        )
    assert caught.value.code == "MARDAS-INVALID-PROJECT-CONTENT"
    assert str(caught.value) == "Project file content must be valid UTF-8 text."


def test_project_save_rejects_non_string_before_cancellable_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_load(*args, **kwargs):
        raise AssertionError("invalid request content must be rejected before project discovery")

    monkeypatch.setattr(application, "_load_workspace_request", unexpected_load)
    with pytest.raises(application.EngineError) as caught:
        application.EngineService().dispatch(
            "project.save",
            {
                "project_path": "/project",
                "relative_path": "chapter.md",
                "content": 123,
                "expected_sha256": "revision",
            },
            cancelled=lambda: True,
        )
    assert caught.value.code == "MARDAS-INVALID-PARAMS"
