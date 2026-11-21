from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mardas_folio.application import EngineService
from mardas_folio.engine_errors import EngineError
from mardas_folio.library import index_path, read_index, write_index


@pytest.fixture(autouse=True)
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARDAS_FOLIO_LIBRARY_DIR", str(tmp_path / "profile"))


def row(path: str, identifier: str = "first") -> dict:
    return {"path": path, "id": identifier, "title": "گلستان", "type": "note", "appearance": {}}


def test_new_profile_and_removal_leave_the_source_alone(tmp_path: Path) -> None:
    source = tmp_path / "قفسه.txt"
    original = "این متن فقط در فایل اصلی است.".encode()
    source.write_bytes(original)
    service = EngineService()
    assert service.dispatch("library.read", {}) == {"revision": 0, "items": []}
    assert not index_path().exists()
    entries = [row(str(source))]
    assert service.dispatch("library.write", {"expected_revision": 0, "items": entries}) == {
        "revision": 1
    }
    assert EngineService().dispatch("library.read", {}) == {"revision": 1, "items": entries}
    assert original not in index_path().read_bytes()
    assert write_index(1, []) == {"revision": 2}
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "alter",
    [
        {"id": ""},
        {"type": "unknown"},
        {"type": []},
        {"title": "x" * 241},
        {"content": "source"},
        {"appearance": {"picture": "https://invalid.example/image.jpg"}},
        {"appearance": {"texture": "felt"}},
        {"appearance": {"color": ["red"]}},
    ],
)
def test_rejects_invalid_rows_without_clobbering_previous_data(alter: dict) -> None:
    before = [row("/one")]
    write_index(0, before)
    with pytest.raises(EngineError) as error:
        write_index(1, [{**before[0], **alter}])
    assert error.value.code == "MARDAS-LIBRARY-INVALID"
    assert read_index() == {"revision": 1, "items": before}


def test_duplicate_path_identity_and_stale_revision() -> None:
    first = row("D:/Mixed/Note.txt")
    with pytest.raises(EngineError):
        write_index(0, [first, row(r"d:\mixed\note.txt", "second")])
    with pytest.raises(EngineError):
        write_index(0, [first, row("/different")])
    write_index(0, [first])
    with pytest.raises(EngineError) as error:
        write_index(0, [])
    assert error.value.code == "MARDAS-LIBRARY-CONFLICT"


def test_separate_writers_commit_one_complete_snapshot() -> None:
    def attempt(i: int) -> str:
        try:
            write_index(0, [row(f"/note{i}")])
            return "saved"
        except EngineError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (1, 2)))
    assert sorted(outcomes) == ["MARDAS-LIBRARY-CONFLICT", "saved"]
    current = read_index()
    assert current["revision"] == 1
    assert current["items"] in ([row("/note1")], [row("/note2")])
