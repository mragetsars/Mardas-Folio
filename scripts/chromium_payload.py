#!/usr/bin/env python3
"""Which parts of a Chromium payload the publishing engine actually needs.

Chromium arrives from Playwright as a complete browser distribution. This
engine uses a narrow slice of it: it hands the browser HTML it generated and
takes back a PDF. Two large pieces of that distribution serve a browser that
has a user interface and a display, and this one has neither.

Shipping them cost users about a quarter of the download for nothing, so the
bundler asks this module what to copy. Everything not named here is kept —
the rule is an explicit exclusion list, not an inclusion list, so a future
Chromium release that adds a file still ships it.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

# Chromium's translated interface strings. The engine renders its own HTML and
# never shows a browser UI, so the only locale that matters is the fallback
# Chromium loads when it cannot find the system one. Verified: with everything
# else removed, a Persian document renders identically under a fa_IR system
# locale, because the browser falls back rather than failing.
KEPT_LOCALES = frozenset({"en-US.pak"})

# The GL and Vulkan backends, including the SwiftShader software emulator.
# The renderer launches with --disable-gpu, so no GPU process starts and none
# of these is loaded. Printing to PDF goes through Skia's vector backend.
DROPPED_FILENAMES = frozenset(
    {
        "libegl.so",
        "libegl.dll",
        "libglesv2.so",
        "libglesv2.dll",
        "libvulkan.so.1",
        "vulkan-1.dll",
        "libvk_swiftshader.so",
        "vk_swiftshader.dll",
        "vk_swiftshader_icd.json",
    }
)


def is_required(relative: PurePosixPath | str) -> bool:
    """Whether a payload-relative path belongs in the shipped browser."""

    relative = PurePosixPath(str(relative).replace("\\", "/"))
    parts = [part.casefold() for part in relative.parts]
    if not parts:
        return False
    if relative.name.casefold() in DROPPED_FILENAMES:
        return False
    if "locales" in parts[:-1] and relative.name not in KEPT_LOCALES:
        # Guard against a layout that keeps something other than a translation
        # inside locales/; only the .pak translations are dropped.
        return relative.suffix.casefold() != ".pak"
    return True


def iter_payload(root: Path) -> Iterator[tuple[Path, str]]:
    """Yield ``(source_file, destination_directory)`` for every kept file.

    The destination is expressed the way PyInstaller's ``datas`` wants it: a
    directory relative to the bundled ``runtime/chromium`` root.
    """

    root = Path(root).resolve(strict=True)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if not is_required(relative):
            continue
        parent = relative.parent
        destination = "runtime/chromium" if parent == PurePosixPath(".") else (
            f"runtime/chromium/{parent}"
        )
        yield path, destination


def contains_symlinks(root: Path) -> bool:
    """Whether the payload's structure depends on links being preserved."""

    return any(path.is_symlink() for path in Path(root).rglob("*"))


def chromium_datas(root: Path) -> list[tuple[str, str]]:
    """The PyInstaller ``datas`` entries for a Chromium payload.

    A macOS ``.app`` holds its framework together with symlinks — a
    ``Versions/Current`` pointing at the real version directory, and the
    top-level entries pointing into it. Enumerating such a tree file by file
    would resolve every link into a second copy of the framework and leave a
    bundle macOS will not launch, so a payload with links is handed over whole
    and keeps everything. The Windows and Linux payloads, and the macOS
    headless shell, are plain directories and get the exclusions.
    """

    root = Path(root).resolve(strict=True)
    if contains_symlinks(root):
        return [(str(root), "runtime/chromium")]
    return [(str(path), destination) for path, destination in iter_payload(root)]


def payload_summary(root: Path) -> dict[str, int]:
    """Byte and file counts before and after the exclusions, for build logs."""

    root = Path(root).resolve(strict=True)
    linked = contains_symlinks(root)
    total_bytes = total_files = kept_bytes = kept_files = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total_bytes += size
        total_files += 1
        if linked or is_required(PurePosixPath(path.relative_to(root).as_posix())):
            kept_bytes += size
            kept_files += 1
    return {
        "total_bytes": total_bytes,
        "total_files": total_files,
        "kept_bytes": kept_bytes,
        "kept_files": kept_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="A Chromium payload directory")
    args = parser.parse_args(argv)
    summary = payload_summary(args.root)
    saved = summary["total_bytes"] - summary["kept_bytes"]
    print(
        f"{summary['total_bytes'] / 1e6:.1f} MB in {summary['total_files']} files"
        f" -> {summary['kept_bytes'] / 1e6:.1f} MB in {summary['kept_files']} files"
        f" (saved {saved / 1e6:.1f} MB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
