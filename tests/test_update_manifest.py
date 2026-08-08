from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "generate_update_manifest.py"
    spec = importlib.util.spec_from_file_location("generate_update_manifest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")


def test_signed_update_manifest_round_trip(tmp_path: Path) -> None:
    module = _load()
    sig_win = tmp_path / "win.sig"
    sig_linux = tmp_path / "linux.sig"
    sig_win.write_text("signed-windows", encoding="utf-8")
    sig_linux.write_text("signed-linux", encoding="utf-8")
    payload = module.build_update_manifest(
        version="1.29.0",
        platform_specs=[
            ("windows-x86_64", "https://example.invalid/windows", sig_win),
            ("linux-x86_64", "https://example.invalid/linux", sig_linux),
        ],
        notes="Release notes",
        pub_date="2026-08-08T00:00:00Z",
    )
    path = tmp_path / "latest.json"
    module.write_manifest(path, payload)
    verified = module.verify_update_manifest(path, expected_version="1.29.0")
    assert verified["version"] == "1.29.0"
    assert list(verified["platforms"]) == ["linux-x86_64", "windows-x86_64"]
    assert verified["platforms"]["windows-x86_64"]["signature"] == "signed-windows"


def test_update_manifest_rejects_insecure_urls_and_duplicate_targets(tmp_path: Path) -> None:
    module = _load()
    sig = tmp_path / "one.sig"
    sig.write_text("signature", encoding="utf-8")
    with pytest.raises(module.UpdateManifestError, match="HTTPS"):
        module.build_update_manifest(
            version="1.29.0",
            platform_specs=[("windows-x86_64", "http://example.invalid/update", sig)],
        )
    with pytest.raises(module.UpdateManifestError, match="Duplicate"):
        module.build_update_manifest(
            version="1.29.0",
            platform_specs=[
                ("windows-x86_64", "https://example.invalid/a", sig),
                ("windows-x86_64", "https://example.invalid/b", sig),
            ],
        )


def test_update_manifest_rejects_missing_or_unknown_signatures(tmp_path: Path) -> None:
    module = _load()
    with pytest.raises(FileNotFoundError):
        module.build_update_manifest(
            version="1.29.0",
            platform_specs=[
                ("windows-x86_64", "https://example.invalid/a", tmp_path / "missing.sig"),
            ],
        )
    sig = tmp_path / "one.sig"
    sig.write_text("signature", encoding="utf-8")
    with pytest.raises(module.UpdateManifestError, match="Unsupported"):
        module.build_update_manifest(
            version="1.29.0",
            platform_specs=[("android-x86_64", "https://example.invalid/a", sig)],
        )


def test_update_manifest_rejects_symlink_signature_input(tmp_path: Path) -> None:
    module = _load()
    target = tmp_path / "real.sig"
    target.write_text("signature", encoding="utf-8")
    link = tmp_path / "linked.sig"
    _symlink_or_skip(link, target)

    with pytest.raises(module.UpdateManifestError, match="missing or unsafe"):
        module.build_update_manifest(
            version="1.29.0",
            platform_specs=[("windows-x86_64", "https://example.invalid/update", link)],
        )


def test_update_manifest_verifier_rejects_symlink_input(tmp_path: Path) -> None:
    module = _load()
    signature = tmp_path / "release.sig"
    signature.write_text("signature", encoding="utf-8")
    payload = module.build_update_manifest(
        version="1.29.0",
        platform_specs=[
            ("windows-x86_64", "https://example.invalid/update", signature),
        ],
    )
    target = tmp_path / "real-latest.json"
    module.write_manifest(target, payload)
    link = tmp_path / "latest.json"
    _symlink_or_skip(link, target)

    with pytest.raises(module.UpdateManifestError, match="missing or unsafe"):
        module.verify_update_manifest(link, expected_version="1.29.0")
