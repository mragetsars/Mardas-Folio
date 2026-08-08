from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_standalone_runtime as runtime_builder  # noqa: E402
import release_provenance as runtime_provenance  # noqa: E402
from build_standalone_runtime import _archive_runtime, _write_manifest  # noqa: E402
from mardas_md2pdf import __version__  # noqa: E402
from release_provenance import (  # noqa: E402
    ReleaseProvenanceError,
    verify_standalone_runtime,
)
from runtime_manifest import (  # noqa: E402
    RUNTIME_FILE_TYPE,
    RUNTIME_MANIFEST_SCHEMA,
    RUNTIME_SYMLINK_TYPE,
)
from stage_desktop_runtime import stage_runtime  # noqa: E402
from verify_standalone_runtime import load_and_verify_manifest  # noqa: E402


def _symlink(link: Path, target: str | Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")


def _file_entry(path: str, data: bytes) -> dict[str, object]:
    return {
        "path": path,
        "type": RUNTIME_FILE_TYPE,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _zip_info(name: str, kind: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
    info.create_system = 3
    permissions = 0o777 if kind == stat.S_IFLNK else 0o644
    info.external_attr = (kind | permissions) << 16
    return info


def _synthetic_archive(
    path: Path,
    *,
    symlinks: dict[str, str],
    symlink_entries: dict[str, str] | None = None,
    include_browser: bool = True,
) -> None:
    root = path.name.removesuffix(".zip")
    files = {"mardas-sidecar": b"sidecar"}
    if include_browser:
        files["runtime/chromium/headless-shell"] = b"chromium"
    entries = [_file_entry(name, data) for name, data in sorted(files.items())]
    entries.extend(
        {
            "path": name,
            "type": RUNTIME_SYMLINK_TYPE,
            "target": target,
        }
        for name, target in sorted((symlink_entries or symlinks).items())
    )
    manifest = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "version": __version__,
        "engine_api_version": "1.0.0",
        "protocol": "mardas-sidecar",
        "protocol_version": 1,
        "browser_bundled": True,
        "files": entries,
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(_zip_info(f"{root}/{name}", stat.S_IFREG), data)
        for name, target in symlinks.items():
            archive.writestr(
                _zip_info(f"{root}/{name}", stat.S_IFLNK),
                target.encode("utf-8"),
            )
        archive.writestr(
            _zip_info(f"{root}/runtime-manifest.json", stat.S_IFREG),
            json.dumps(manifest, sort_keys=True).encode("utf-8"),
        )


def test_safe_symlinks_are_manifested_staged_and_archived_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / f"Mardas-MD2PDF-{__version__}-runtime-linux-x86_64"
    internal = runtime / "_internal"
    browser = runtime / "runtime" / "chromium"
    internal.mkdir(parents=True)
    browser.mkdir(parents=True)
    (runtime / "mardas-sidecar").write_bytes(b"sidecar")
    library = internal / "libengine.so.1"
    library.write_bytes(b"library")
    nested_manifest = internal / "runtime-manifest.json"
    nested_manifest.write_bytes(b"dependency-data")
    (runtime / "libshared.so.1").write_bytes(b"shared-library")
    (browser / "headless-shell").write_bytes(b"chromium")
    _symlink(internal / "libengine.so", "libengine.so.1")
    _symlink(internal / "libshared.so", "../libshared.so.1")
    _symlink(runtime / "browser-current", "runtime/chromium", directory=True)

    manifest_path = _write_manifest(runtime, browser_source=browser)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == RUNTIME_MANIFEST_SCHEMA
    by_path = {entry["path"]: entry for entry in manifest["files"]}
    assert by_path["_internal/libengine.so"] == {
        "path": "_internal/libengine.so",
        "type": RUNTIME_SYMLINK_TYPE,
        "target": "libengine.so.1",
    }
    assert by_path["_internal/libshared.so"]["target"] == "../libshared.so.1"
    assert by_path["_internal/runtime-manifest.json"] == _file_entry(
        "_internal/runtime-manifest.json",
        nested_manifest.read_bytes(),
    )
    assert by_path["browser-current"]["target"] == "runtime/chromium"
    load_and_verify_manifest(runtime, expected_version=__version__, require_browser=True)

    staged = stage_runtime(
        runtime,
        tmp_path / "tauri-resources" / "sidecar",
        expected_version=__version__,
    )
    assert (staged / "_internal" / "libengine.so").is_symlink()
    assert os.readlink(staged / "_internal" / "libengine.so") == "libengine.so.1"
    assert os.readlink(staged / "_internal" / "libshared.so") == "../libshared.so.1"
    assert (staged / "browser-current").is_symlink()
    assert (staged / "browser-current").resolve(strict=True).is_dir()

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1735689600")
    first = tmp_path / f"{runtime.name}.zip"
    second = tmp_path / f"second-{runtime.name}.zip"
    _archive_runtime(runtime, first)
    os.utime(library, (1_800_000_000, 1_800_000_000))
    _archive_runtime(runtime, second)
    assert first.read_bytes() == second.read_bytes()

    expected_time = time.gmtime(1_735_689_600)[:6]
    with zipfile.ZipFile(first) as archive:
        link_name = f"{runtime.name}/_internal/libengine.so"
        link_info = archive.getinfo(link_name)
        assert (link_info.external_attr >> 16) & 0o170000 == stat.S_IFLNK
        assert archive.read(link_name) == b"libengine.so.1"
        assert all(info.date_time == expected_time for info in archive.infolist())
    verify_standalone_runtime(first, expected_version=__version__)


def test_browser_claim_requires_regular_inventory_evidence(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    sidecar = runtime / "mardas-sidecar"
    sidecar.write_bytes(b"sidecar")

    with pytest.raises(RuntimeError, match="no regular browser file"):
        _write_manifest(runtime, browser_source=tmp_path / "chromium-source")

    manifest = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "version": __version__,
        "browser_bundled": True,
        "files": [_file_entry("mardas-sidecar", sidecar.read_bytes())],
    }
    (runtime / "runtime-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="without an inventoried browser file"):
        load_and_verify_manifest(runtime, expected_version=__version__)

    archive = tmp_path / f"Mardas-MD2PDF-{__version__}-runtime-no-browser.zip"
    _synthetic_archive(archive, symlinks={}, include_browser=False)
    with pytest.raises(ReleaseProvenanceError, match="without an inventoried browser file"):
        verify_standalone_runtime(archive, expected_version=__version__)


def test_runtime_file_limit_excludes_the_root_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / f"Mardas-MD2PDF-{__version__}-runtime-boundary"
    browser = runtime / "runtime" / "chromium"
    browser.mkdir(parents=True)
    (runtime / "mardas-sidecar").write_bytes(b"sidecar")
    (browser / "headless-shell").write_bytes(b"chromium")
    _write_manifest(runtime, browser_source=browser)

    monkeypatch.setattr(runtime_builder, "MAX_RUNTIME_FILES", 2)
    archive = tmp_path / f"{runtime.name}.zip"
    _archive_runtime(runtime, archive)

    monkeypatch.setattr(runtime_provenance, "MAX_STANDALONE_FILES", 2)
    verify_standalone_runtime(archive, expected_version=__version__)


@pytest.mark.parametrize(
    "case", ["absolute", "escape", "dangling", "cycle", "directory-cycle"]
)
def test_manifest_builder_rejects_unsafe_symlinks(tmp_path: Path, case: str) -> None:
    runtime = tmp_path / case
    runtime.mkdir()
    (runtime / "mardas-sidecar").write_bytes(b"sidecar")
    target = runtime / "target.bin"
    target.write_bytes(b"target")
    outside = tmp_path / f"outside-{case}.bin"
    outside.write_bytes(b"outside")

    if case == "absolute":
        _symlink(runtime / "unsafe", target.resolve())
    elif case == "escape":
        links = runtime / "links"
        links.mkdir()
        _symlink(links / "unsafe", "../../outside-escape.bin")
    elif case == "dangling":
        _symlink(runtime / "unsafe", "missing.bin")
    elif case == "cycle":
        _symlink(runtime / "first", "second")
        _symlink(runtime / "second", "first")
    else:
        first_dir = runtime / "first-dir"
        second_dir = runtime / "second-dir"
        first_dir.mkdir()
        second_dir.mkdir()
        _symlink(first_dir / "to-second", "../second-dir", directory=True)
        _symlink(second_dir / "to-first", "../first-dir", directory=True)

    with pytest.raises(ValueError, match="relative|root|dangling|cyclic|cycle"):
        _write_manifest(runtime, browser_source=None)


def test_directory_verifier_checks_lstat_before_following_a_link(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    sidecar = runtime / "mardas-sidecar"
    sidecar.write_bytes(b"sidecar")
    browser = runtime / "browser.bin"
    browser.write_bytes(b"chromium")
    alias = runtime / "alias.bin"
    _symlink(alias, "browser.bin")
    manifest = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "version": __version__,
        "browser_bundled": True,
        "files": [
            _file_entry("mardas-sidecar", sidecar.read_bytes()),
            _file_entry("browser.bin", browser.read_bytes()),
            _file_entry("alias.bin", browser.read_bytes()),
        ],
    }
    (runtime / "runtime-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="missing or unsafe"):
        load_and_verify_manifest(runtime, expected_version=__version__)


@pytest.mark.parametrize(
    ("name", "symlinks", "manifest_links", "message"),
    [
        ("absolute", {"links/a": "/etc/passwd"}, None, "target is invalid"),
        ("escape", {"links/a": "../../outside"}, None, "escapes"),
        ("dangling", {"links/a": "missing"}, None, "dangling"),
        ("cycle", {"links/a": "b", "links/b": "a"}, None, "cycle"),
        ("component-cycle", {"a": "a/.."}, None, "cycle"),
        ("missing-component", {"a": "missing/.."}, None, "dangling"),
        (
            "mismatch",
            {"links/a": "../mardas-sidecar"},
            {"links/a": "../runtime/chromium/headless-shell"},
            "target mismatch",
        ),
    ],
)
def test_release_provenance_rejects_unsafe_or_mismatched_symlinks(
    tmp_path: Path,
    name: str,
    symlinks: dict[str, str],
    manifest_links: dict[str, str] | None,
    message: str,
) -> None:
    archive = tmp_path / f"Mardas-MD2PDF-{__version__}-runtime-{name}.zip"
    _synthetic_archive(
        archive,
        symlinks=symlinks,
        symlink_entries=manifest_links,
    )
    with pytest.raises(ReleaseProvenanceError, match=message):
        verify_standalone_runtime(archive, expected_version=__version__)
