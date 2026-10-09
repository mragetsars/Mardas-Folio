from __future__ import annotations

import pytest

from mardas_folio import application


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
