from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from chromium_payload import (  # noqa: E402
    KEPT_LOCALES,
    chromium_datas,
    contains_symlinks,
    is_required,
    payload_summary,
)


def _payload(root: Path, *, symlink: bool = False) -> Path:
    """A miniature of what Playwright unpacks for chrome-headless-shell."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "chrome-headless-shell").write_bytes(b"x" * 4096)
    (root / "icudtl.dat").write_bytes(b"i" * 2048)
    (root / "headless_lib_strings.pak").write_bytes(b"s" * 512)
    (root / "v8_context_snapshot.bin").write_bytes(b"v" * 256)
    (root / "libGLESv2.so").write_bytes(b"g" * 1024)
    (root / "libEGL.so").write_bytes(b"e" * 128)
    (root / "libvulkan.so.1").write_bytes(b"k" * 128)
    (root / "libvk_swiftshader.so").write_bytes(b"w" * 512)
    (root / "vk_swiftshader_icd.json").write_text("{}", encoding="utf-8")
    hyphens = root / "hyphen-data"
    hyphens.mkdir(exist_ok=True)
    (hyphens / "hyph-fa.hyb").write_bytes(b"h" * 64)
    locales = root / "locales"
    locales.mkdir(exist_ok=True)
    for name in ("en-US", "fa", "de", "ja", "en-GB"):
        (locales / f"{name}.pak").write_bytes(b"l" * 256)
    if symlink:
        (root / "Current").symlink_to("chrome-headless-shell")
    return root


def test_the_engine_keeps_what_it_renders_with(tmp_path: Path) -> None:
    """Fonts, hyphenation and ICU decide how Persian text is shaped."""

    for name in (
        "chrome-headless-shell",
        "icudtl.dat",
        "headless_lib_strings.pak",
        "v8_context_snapshot.bin",
        "hyphen-data/hyph-fa.hyb",
        "locales/en-US.pak",
    ):
        assert is_required(name), f"{name} is needed to render"


def test_the_translated_interface_and_gpu_backends_are_dropped() -> None:
    """Neither is reachable: no UI is shown and the launch disables the GPU."""

    for name in ("locales/fa.pak", "locales/de.pak", "locales/en-GB.pak"):
        assert not is_required(name)
    for name in (
        "libGLESv2.so",
        "libEGL.so",
        "libvulkan.so.1",
        "libvk_swiftshader.so",
        "vk_swiftshader_icd.json",
    ):
        assert not is_required(name)
    # Windows ships the same backends under different filenames.
    for name in ("libGLESv2.dll", "vulkan-1.dll", "vk_swiftshader.dll"):
        assert not is_required(name)


def test_a_non_translation_inside_locales_is_still_shipped() -> None:
    """The exclusion targets translations, not the directory."""

    assert is_required("locales/README")
    assert is_required("locales/index.json")


def test_payload_entries_land_under_the_bundled_browser_root(tmp_path: Path) -> None:
    root = _payload(tmp_path / "chrome-headless-shell-linux64")

    entries = chromium_datas(root)
    destinations = {destination for _, destination in entries}
    names = {Path(source).name for source, _ in entries}

    assert destinations == {"runtime/chromium", "runtime/chromium/hyphen-data",
                            "runtime/chromium/locales"}
    assert "chrome-headless-shell" in names
    assert "hyph-fa.hyb" in names
    assert names & {f"{locale}" for locale in KEPT_LOCALES} == set(KEPT_LOCALES)
    assert "fa.pak" not in names
    assert "libGLESv2.so" not in names


def test_a_payload_held_together_by_symlinks_is_copied_whole(tmp_path: Path) -> None:
    """A macOS .app framework resolves into a broken duplicate if enumerated.

    Its top-level entries are links into Versions/Current, so copying file by
    file would both double the size and produce a bundle macOS will not launch.
    """

    root = _payload(tmp_path / "Chromium.app", symlink=True)

    assert contains_symlinks(root)
    assert chromium_datas(root) == [(str(root.resolve()), "runtime/chromium")]
    summary = payload_summary(root)
    assert summary["kept_bytes"] == summary["total_bytes"]
    assert summary["kept_files"] == summary["total_files"]


def test_the_summary_reports_what_the_exclusions_save(tmp_path: Path) -> None:
    root = _payload(tmp_path / "chrome-headless-shell-linux64")

    summary = payload_summary(root)

    assert summary["kept_bytes"] < summary["total_bytes"]
    assert summary["kept_files"] < summary["total_files"]
    # Four translations and five GPU files.
    assert summary["total_files"] - summary["kept_files"] == 9


@pytest.mark.parametrize("value", ["", "."])
def test_an_empty_relative_path_is_not_treated_as_a_file(value: str) -> None:
    assert is_required(value) is False
