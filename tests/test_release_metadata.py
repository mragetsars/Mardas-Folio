from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _project_version() -> str:
    match = re.search(r'^version = "([^"]+)"', _read("pyproject.toml"), re.MULTILINE)
    assert match, "project.version is missing from pyproject.toml"
    return match.group(1)


def test_project_version_metadata_matches() -> None:
    version = _project_version()

    assert f'__version__ = "{version}"' in _read("src/mardas_md2pdf/__init__.py")
    assert f"Version-v{version}-success" in _read("README.md")
    assert f'version: "{version}"' in _read("docs/guides/GUIDE.en.md")
    assert f'version: "{version}"' in _read("docs/guides/GUIDE.fa.md")
    assert re.search(
        rf"^## {re.escape(version)} - \d{{4}}-\d{{2}}-\d{{2}}",
        _read("docs/CHANGELOG.md"),
        re.MULTILINE,
    )


def test_visual_qa_fixtures_use_the_project_version() -> None:
    for relative_path in (
        "scripts/audit_appearance_matrix.py",
        "scripts/audit_pdf_features.py",
    ):
        script = _read(relative_path)
        assert "from mardas_md2pdf import __version__" in script
        assert "__MARDAS_VERSION__" in script
        assert "1.13.2" not in script
        assert "1.13.11" not in script


def test_maintenance_scripts_are_executable() -> None:
    for relative_path in [
        "scripts/install_playwright.sh",
        "scripts/check.sh",
        "scripts/render_smoke.py",
        "scripts/build_examples.sh",
        "scripts/build_dist.sh",
        "scripts/normalize_sdist.py",
        "scripts/clean_workspace.sh",
        "scripts/release_gate.sh",
        "scripts/release_provenance.py",
        "scripts/generate_sbom.py",
        "scripts/finalize_release_artifacts.py",
        "scripts/build_offline_bundle.py",
        "scripts/cross_platform_smoke.py",
    ]:
        path = ROOT / relative_path
        assert path.is_file()
        assert os.access(path, os.X_OK)


def test_release_docs_reference_maintenance_scripts() -> None:
    release_doc = _read("docs/RELEASE.md")
    maintenance_doc = _read("docs/MAINTENANCE.md")
    readme = _read("README.md")

    for command in [
        "./scripts/check.sh",
        "./scripts/build_examples.sh",
        "./scripts/build_dist.sh",
        "./scripts/clean_workspace.sh",
    ]:
        assert command in release_doc
        assert command in maintenance_doc

    assert "docs/MAINTENANCE.md" in readme
    assert "Release Artifacts" in release_doc


def test_example_builds_set_deterministic_pdf_dates() -> None:
    script = ROOT.joinpath("scripts", "build_examples.sh").read_text(encoding="utf-8")

    assert "SOURCE_DATE_EPOCH" in script
    assert "1735689600" in script
    assert "mardas_md2pdf.cli" in script
    assert "docs/guides/GUIDE.en.md" in script
    assert "docs/guides/GUIDE.fa.md" in script
    assert "run_command" in script
    assert "--progress" in script
    for option in ["--style", "modern", "--palette", "emerald", "--mode", "light"]:
        assert option in script
    assert '"--palette",\n        "blue"' not in script


def test_build_dist_supports_no_isolation_mode() -> None:
    script = ROOT.joinpath("scripts", "build_dist.sh").read_text(encoding="utf-8")

    assert "MARDAS_BUILD_NO_ISOLATION" in script
    assert "python -m build --no-isolation" in script
    assert "setuptools import build_meta" in script
    assert "build_with_current_setuptools_backend" in script
    assert "MARDAS_BUILD_NO_ISOLATION=1 bash scripts/build_dist.sh" in script
    assert "SOURCE_DATE_EPOCH" in script
    assert "PYTHONHASHSEED" in script
    assert 'TZ="${TZ:-UTC}"' in script
    assert "scripts/normalize_sdist.py" in script



def test_normalize_sdist_preserves_archive_permissions(tmp_path: Path) -> None:
    archive = tmp_path / "sample.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("release payload", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as target:
        target.add(payload, arcname="sample/payload.txt")
    archive.chmod(0o644)

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "normalize_sdist.py"),
            str(archive),
            "--epoch",
            "1735689600",
        ],
        check=True,
    )

    assert stat.S_IMODE(archive.stat().st_mode) == 0o644


def test_pytest_can_import_src_from_checkout() -> None:
    pyproject = _read("pyproject.toml")

    assert 'pythonpath = ["src"]' in pyproject
    assert 'testpaths = ["tests"]' in pyproject


def test_source_distribution_manifest_includes_release_support_files() -> None:
    manifest = _read("MANIFEST.in")

    for expected in [
        "recursive-include docs *.md *.png *.bib *.json",
        "recursive-include examples *.pdf",
        "recursive-include scripts *.py *.sh",
        "recursive-include tests *.py",
        "recursive-include .github *.yml",
        "prune build",
        "prune dist",
        "prune patches",
    ]:
        assert expected in manifest


def test_release_gate_consolidates_release_checks() -> None:
    script = ROOT.joinpath("scripts", "release_gate.sh").read_text(encoding="utf-8")
    release_doc = _read("docs/RELEASE.md")

    assert "scripts/check.sh" in script
    assert "MARDAS_RELEASE_SMOKE_TIMEOUT" in script
    assert "scripts/build_examples.sh" in script
    assert "scripts/check_pdf_preflight.py" in script
    assert "scripts/run_visual_qa_matrix.py" in script
    assert "scripts/build_dist.sh" in script
    assert "MARDAS_RELEASE_VISUAL_QA" in script
    assert "python -m venv" in script
    assert "pip check" in script
    assert "scripts/generate_sbom.py" in script
    assert "scripts/finalize_release_artifacts.py" in script
    assert "--require-sbom" in script
    assert "./scripts/release_gate.sh" in release_doc


def test_release_workflow_runs_the_complete_release_gate() -> None:
    workflow = _read(".github/workflows/release.yml")

    assert "./scripts/release_gate.sh" in workflow
    assert "MARDAS_RELEASE_VISUAL_QA: '1'" in workflow
    assert "./scripts/check.sh" not in workflow
    assert "scripts/build_offline_bundle.py" in workflow
    assert "scripts/finalize_release_artifacts.py" in workflow
    assert "actions/attest@v4" in workflow
    assert "subject-checksums" in workflow
    assert "sbom-path" in workflow


def test_check_render_smoke_uses_process_tree_safe_command_runner() -> None:
    check_script = ROOT.joinpath("scripts", "check.sh").read_text(encoding="utf-8")
    smoke_script = ROOT.joinpath("scripts", "render_smoke.py").read_text(encoding="utf-8")

    assert "python scripts/render_smoke.py" in check_script
    assert "MARDAS_RENDER_SMOKE=0 python -m pytest" in check_script
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in check_script
    assert "MARDAS_ALLOW_PYTEST_PLUGINS" in check_script
    assert "from visual_qa import run_command" in smoke_script
    assert "MARDAS_RENDER_SMOKE_TIMEOUT" in smoke_script
    assert 'description="render smoke"' in smoke_script


def test_release_gate_verifies_installed_project_commands() -> None:
    script = _read("scripts/release_gate.sh")

    for command in [
        " init ",
        " validate ",
        " explain-config ",
        " doctor ",
        " validate-book ",
        " explain-book ",
        " build-book ",
    ]:
        assert command in script
    assert "--book" in script
    assert "project_smoke" in script
    assert "validate.json" in script
    assert "dist/book.pdf" in script
    assert "numbered_objects" in script
    assert "cited_entries" in script
    assert "bibliography_entries" in script
    assert "references.bib" in script
    assert "bib-" in script
    assert "mardas_md2pdf.workspace" in script
    assert "workspace_payload" in script
    assert 'grep -F -- "--project"' in script
    assert "scripts/audit_studio_visual.py" in script
    assert "build/release/studio-project" in script
    assert "RenderSession" in script
    assert "RenderPool" in script
    assert "Persistent-renderer smoke" in script
    assert "render_pool.py" in script
    assert "studio_jobs.py" in script
    assert "xref-fig-model" in script
    assert "xref-tbl-metrics" in script
    assert "xref-eq-energy" in script
    assert "xref-lst-loop" in script
    assert "tests/test_cross_references.py" in _read("docs/RELEASE.md")
    assert "tests/test_cross_references.py" in _read("docs/MAINTENANCE.md")
    assert "tests/test_citations.py" in _read("docs/RELEASE.md")
    assert "tests/test_citations.py" in _read("docs/MAINTENANCE.md")


def test_release_gate_verifies_current_packaged_asset_names() -> None:
    script = _read("scripts/release_gate.sh")

    for asset in [
        "style-modern.css",
        "style-github.css",
        "style-textbook.css",
        "style-academic.css",
        "mardas-md2pdf-mark.svg",
        "mathjax/tex-svg-full.js",
    ]:
        assert asset in script
    for obsolete in ["base.css", "style_modern.css", "mardas-logo.svg"]:
        assert obsolete not in script


def test_release_gate_verifies_accessibility_and_archival_audits() -> None:
    script = _read("scripts/release_gate.sh")
    for command in (
        "audit-accessibility",
        "audit-book-accessibility",
        "audit-pdf",
    ):
        assert command in script
    assert "audit-accessibility.json" in script
    assert "audit-book-accessibility.json" in script
    assert "audit-pdf.json" in script
    assert "compliance_claims" in script
    assert "pdfua" in script

    release_doc = _read("docs/RELEASE.md")
    assert "Accessibility and archival-readiness release checks" in release_doc
    assert "independent validator" in release_doc


def test_release_docs_describe_sbom_attestations_and_offline_bundles() -> None:
    release_doc = _read("docs/RELEASE.md")
    maintenance_doc = _read("docs/MAINTENANCE.md")
    security_doc = _read("docs/SECURITY.md")
    readme = _read("README.md")

    for marker in (
        "SPDX 2.3",
        "RELEASE-MANIFEST.json",
        "CHECKSUMS.sha256",
        "scripts/build_offline_bundle.py",
        "gh attestation verify",
    ):
        assert marker in release_doc
    assert "Cross-platform distribution and provenance" in release_doc
    assert "Release supply-chain boundary" in security_doc
    assert "Release Verification and Offline Bundles" in readme
    assert "offline Python bundle" in maintenance_doc
    assert "Chromium is intentionally excluded" in maintenance_doc
