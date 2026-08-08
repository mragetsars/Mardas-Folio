from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from mardas_md2pdf import __version__
from mardas_md2pdf.application import ENGINE_API_VERSION, EngineService
from mardas_md2pdf.support import SupportBundleError, create_support_bundle


def test_support_bundle_is_privacy_safe_and_versioned(tmp_path: Path) -> None:
    output = tmp_path / "support.zip"
    result = create_support_bundle(output, engine_api_version=ENGINE_API_VERSION)

    assert result["output_path"] == str(output.resolve())
    assert result["size_bytes"] > 0
    assert len(result["sha256"]) == 64
    assert result["privacy"] == {
        "document_content_included": False,
        "document_paths_included": False,
        "environment_variables_included": False,
        "home_directory_included": False,
    }

    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"README.txt", "support.json"}
        payload = json.loads(archive.read("support.json"))
        readme = archive.read("README.txt").decode("utf-8")

    assert payload["schema_version"] == 1
    assert payload["version"] == __version__
    assert payload["engine_api_version"] == ENGINE_API_VERSION
    assert "executable" not in payload["runtime"]
    assert "runtime_root" not in payload["runtime"]
    assert "bundle_root" not in payload["runtime"]
    assert str(Path.home()) not in json.dumps(payload)
    assert "document contents" in readme.lower()


def test_support_bundle_requires_zip_extension_and_existing_parent(tmp_path: Path) -> None:
    with pytest.raises(SupportBundleError, match=r"\.zip"):
        create_support_bundle(tmp_path / "support.txt", engine_api_version=ENGINE_API_VERSION)

    with pytest.raises(SupportBundleError, match="does not exist"):
        create_support_bundle(
            tmp_path / "missing" / "support.zip",
            engine_api_version=ENGINE_API_VERSION,
        )


def test_engine_service_dispatches_support_bundle(tmp_path: Path) -> None:
    service = EngineService()
    output = tmp_path / "Mardas-Support.zip"
    result = service.dispatch(
        "system.support_bundle",
        {"output_path": str(output)},
    )
    assert output.is_file()
    assert result["output_path"] == str(output.resolve())
    assert "system.support_bundle" in service.capabilities()["methods"]
