from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _project_version() -> str:
    match = re.search(r'^version = "([^"]+)"', _read("pyproject.toml"), re.MULTILINE)
    assert match, "project.version is missing from pyproject.toml"
    return match.group(1)


def test_project_version_metadata_matches() -> None:
    version = _project_version()

    assert f'__version__ = "{version}"' in _read("src/mardas_folio/__init__.py")
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
        assert "from mardas_folio import __version__" in script
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
        "scripts/build_standalone_runtime.py",
        "scripts/verify_standalone_runtime.py",
        "scripts/build_desktop_frontend.py",
        "scripts/verify_desktop_frontend.py",
        "scripts/stage_desktop_runtime.py",
        "scripts/generate_desktop_icons.py",
        "scripts/build_desktop_app.py",
        "scripts/verify_desktop_installer.py",
        "scripts/build_native_desktop.py",
        "scripts/verify_native_desktop.py",
        "scripts/generate_update_manifest.py",
        "scripts/assemble_signed_updates.py",
        "scripts/release_preflight.py",
        "scripts/verify_platform_signing.py",
        "scripts/extract_release_notes.py",
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
    assert "mardas_folio.cli" in script
    assert "docs/guides/GUIDE.en.md" in script
    assert "docs/guides/GUIDE.fa.md" in script
    assert "run_command" in script
    assert "--progress" in script
    # Amber is the palette closest to the product's own accent: its dark accent
    # is the brand orange exactly, so the published guides look like the
    # application that produced them.
    for option in ["--style", "modern", "--palette", "amber", "--mode", "light"]:
        assert option in script
    assert '"--palette",\n        "emerald"' not in script


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


def test_python_build_backend_is_security_fixed_and_reproducible() -> None:
    metadata = tomllib.loads(_read("pyproject.toml"))

    assert metadata["build-system"]["requires"] == [
        "setuptools==83.0.0",
        "wheel==0.47.0",
    ]
    assert "setuptools==83.0.0" in metadata["project"]["optional-dependencies"]["dev"]
    assert "wheel==0.47.0" in metadata["project"]["optional-dependencies"]["dev"]



def test_normalize_sdist_preserves_archive_permissions(tmp_path: Path) -> None:
    archive = tmp_path / "sample.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("release payload", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as target:
        target.add(payload, arcname="sample/payload.txt")
    archive.chmod(0o644)
    # What matters is that normalization hands the archive back with the mode
    # it was given, whatever that mode is. Windows maps `chmod` onto a single
    # read-only flag and reports 0o666 for every writable file, so asserting
    # the POSIX value here would only be testing the filesystem.
    original_mode = stat.S_IMODE(archive.stat().st_mode)

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

    assert stat.S_IMODE(archive.stat().st_mode) == original_mode


def test_pytest_can_import_src_from_checkout() -> None:
    pyproject = _read("pyproject.toml")

    assert 'pythonpath = ["src"]' in pyproject
    assert 'testpaths = ["tests"]' in pyproject


def test_source_distribution_manifest_includes_release_support_files() -> None:
    manifest = _read("MANIFEST.in")

    for expected in [
        "include pyrightconfig.json",
        "include apps/desktop/src-tauri/Cargo.lock",
        "recursive-include docs *.md *.png *.bib *.json",
        "recursive-include examples *.pdf",
        "recursive-include scripts *.py *.sh",
        "recursive-include packaging *.py *.spec",
        "recursive-include schemas *.json",
        "recursive-include tests *.py",
        "recursive-include apps *.html *.css *.mjs *.json *.toml *.rs *.png *.ico *.icns *.svg *.md",
        "prune apps/desktop/node_modules",
        "prune apps/desktop/dist",
        "prune apps/desktop/src-tauri/target",
        "prune apps/desktop/src-tauri/resources/sidecar",
        "include apps/desktop/src-tauri/resources/sidecar/README.md",
        "recursive-include .github *.yml",
        "prune build",
        "prune dist",
        "prune patches",
    ]:
        assert expected in manifest


def test_tauri_before_build_command_resolves_from_desktop_root() -> None:
    config = json.loads(_read("apps/desktop/src-tauri/tauri.conf.json"))

    command = config["build"]["beforeBuildCommand"]

    assert command == "python ../../scripts/build_desktop_frontend.py"

    script_path = (
        ROOT
        / "apps"
        / "desktop"
        / "../../scripts/build_desktop_frontend.py"
    ).resolve()

    assert script_path == (ROOT / "scripts/build_desktop_frontend.py").resolve()
    assert script_path.is_file()


def test_native_desktop_builds_use_the_committed_cargo_lock() -> None:
    native = _read("scripts/build_native_desktop.py")
    legacy = _read("scripts/build_desktop_app.py")
    ci = _read(".github/workflows/ci.yml")
    release = _read(".github/workflows/release.yml")

    assert 'command.extend(["--", "--locked"])' in native
    assert '"nsis", "--", "--locked"' in legacy
    assert "dtolnay/rust-toolchain@1.97.1" in ci
    assert "dtolnay/rust-toolchain@1.97.1" in release
    assert "dtolnay/rust-toolchain@stable" not in ci + release
    assert ci.count("cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked") == 2


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


def test_dependency_audit_skips_the_local_editable_project() -> None:
    script = _read("scripts/security_audit.sh")

    assert "--strict" in script
    assert "--exclude-editable" in script
    assert "--no-deps" in script
    assert "--disable-pip" in script
    assert "pip freeze --all" in script
    assert "editable_project_location" in script
    assert '--requirement "$requirements"' in script


def _run_security_audit_harness(
    case_dir: Path,
    *,
    editables: list[dict[str, str]] | None = None,
    freeze: str = "packaging==25.0\npip==25.1\n",
    audit_exit: int = 0,
    audit_payload: str = '{"dependencies": []}\n',
) -> tuple[subprocess.CompletedProcess[str], Path, list[list[str]], str | None]:
    case_dir.mkdir(parents=True, exist_ok=True)
    fake_bin = case_dir / "bin"
    fake_bin.mkdir()
    driver = case_dir / "fake_python.py"
    driver.write_text(
        """from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


args = sys.argv[1:]
with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")

if args == ["-m", "pip", "list", "--editable", "--format=json"]:
    sys.stdout.write(os.environ["FAKE_EDITABLES_JSON"])
    raise SystemExit(0)
if args == ["-m", "pip", "freeze", "--all", "--exclude-editable"]:
    sys.stdout.write(os.environ["FAKE_FREEZE_TEXT"])
    raise SystemExit(0)
if args[:2] == ["-m", "pip_audit"]:
    expected_flags = [
        "--strict",
        "--no-deps",
        "--disable-pip",
        "--requirement",
    ]
    if args[2:6] != expected_flags or args[7:9] != ["--format", "json"] or args[9] != "--output":
        raise SystemExit("Unexpected pip-audit arguments")
    final_output = Path(os.environ["FAKE_FINAL_OUTPUT"])
    observation = Path(os.environ["FAKE_AUDIT_OBSERVATION"])
    observation.write_text("present" if final_output.exists() else "absent", encoding="utf-8")
    audit_output = Path(args[10])
    audit_output.write_text(os.environ["FAKE_AUDIT_PAYLOAD"], encoding="utf-8")
    raise SystemExit(int(os.environ["FAKE_AUDIT_EXIT"]))
if args and args[0] == "-":
    completed = subprocess.run(
        [os.environ["MARDAS_REAL_PYTHON"], *args],
        stdin=sys.stdin,
        check=False,
    )
    raise SystemExit(completed.returncode)
raise SystemExit(f"Unexpected fake-python invocation: {args!r}")
""",
        encoding="utf-8",
    )
    fake_python = fake_bin / "python"
    fake_python.write_text(
        '#!/usr/bin/env bash\nexec "$MARDAS_REAL_PYTHON" "$MARDAS_FAKE_PYTHON_DRIVER" "$@"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    output = case_dir / "published" / "pip-audit.json"
    output.parent.mkdir()
    output.write_text("stale-success", encoding="utf-8")
    call_log = case_dir / "calls.jsonl"
    observation = case_dir / "audit-observation.txt"
    temp_root = case_dir / "tmp"
    temp_root.mkdir()
    if editables is None:
        editables = [
            {
                "name": "Mardas_Folio",
                "version": "1.26.0",
                "editable_project_location": str(ROOT),
            }
        ]

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "TMPDIR": str(temp_root),
            "MARDAS_SECURITY_AUDIT_OUTPUT": str(output),
            "MARDAS_REAL_PYTHON": sys.executable,
            "MARDAS_FAKE_PYTHON_DRIVER": str(driver),
            "FAKE_EDITABLES_JSON": json.dumps(editables),
            "FAKE_FREEZE_TEXT": freeze,
            "FAKE_AUDIT_EXIT": str(audit_exit),
            "FAKE_AUDIT_PAYLOAD": audit_payload,
            "FAKE_CALL_LOG": str(call_log),
            "FAKE_FINAL_OUTPUT": str(output),
            "FAKE_AUDIT_OBSERVATION": str(observation),
        }
    )
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts/security_audit.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    observed = observation.read_text(encoding="utf-8") if observation.exists() else None
    return completed, output, calls, observed


@pytest.mark.skipif(os.name == "nt", reason="The security audit is a POSIX Bash CI job")
def test_dependency_audit_requires_exact_checkout_editable(tmp_path: Path) -> None:
    valid = {
        "name": "mardas-folio",
        "version": "1.26.0",
        "editable_project_location": str(ROOT),
    }
    invalid_inventories = [
        [],
        [valid, {"name": "other", "version": "1.0", "editable_project_location": str(ROOT)}],
        [{**valid, "editable_project_location": str(tmp_path)}],
    ]

    for index, inventory in enumerate(invalid_inventories):
        completed, output, calls, _ = _run_security_audit_harness(
            tmp_path / f"editable-{index}",
            editables=inventory,
        )

        assert completed.returncode != 0
        assert not output.exists()
        assert not any(call[:2] == ["-m", "pip_audit"] for call in calls)


@pytest.mark.skipif(os.name == "nt", reason="The security audit is a POSIX Bash CI job")
@pytest.mark.parametrize(
    "freeze",
    [
        "sample @ https://example.invalid/sample.whl\n",
        "sample>=1.0\n",
    ],
    ids=["url", "non-pin"],
)
def test_dependency_audit_rejects_urls_and_non_pins(tmp_path: Path, freeze: str) -> None:
    completed, output, calls, _ = _run_security_audit_harness(tmp_path, freeze=freeze)

    assert completed.returncode != 0
    assert "not an exact registry pin" in completed.stderr
    assert not output.exists()
    assert not any(call[:2] == ["-m", "pip_audit"] for call in calls)


@pytest.mark.skipif(os.name == "nt", reason="The security audit is a POSIX Bash CI job")
def test_dependency_audit_failure_removes_stale_report(tmp_path: Path) -> None:
    completed, output, _, observed = _run_security_audit_harness(
        tmp_path,
        audit_exit=1,
        audit_payload='{"partial": true',
    )

    assert completed.returncode == 1
    assert observed == "absent"
    assert not output.exists()
    assert not list(output.parent.glob(".pip-audit-result.*"))
    assert not list((tmp_path / "tmp").glob("mardas-pip-audit.*"))


@pytest.mark.skipif(os.name == "nt", reason="The security audit is a POSIX Bash CI job")
def test_dependency_audit_success_publishes_atomically(tmp_path: Path) -> None:
    payload = '{"dependencies": []}\n'
    completed, output, calls, observed = _run_security_audit_harness(
        tmp_path,
        audit_payload=payload,
    )

    assert completed.returncode == 0, completed.stderr
    assert observed == "absent"
    assert output.read_text(encoding="utf-8") == payload
    audit_calls = [call for call in calls if call[:2] == ["-m", "pip_audit"]]
    assert len(audit_calls) == 1
    audit_temp = Path(audit_calls[0][audit_calls[0].index("--output") + 1])
    assert audit_temp.parent == output.parent
    assert audit_temp != output
    assert audit_temp.name.startswith(".pip-audit-result.")
    assert not audit_temp.exists()
    assert not list(output.parent.glob(".pip-audit-result.*"))


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
    assert 'scripts/release_preflight.py --mode "$MARDAS_RELEASE_MODE"' in workflow
    assert "--create-updater-artifacts" in workflow
    assert "scripts/assemble_signed_updates.py" in workflow
    assert "--require-update-manifest" in workflow
    assert "publish-draft:" in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow
    # poppler-utils backs `--render-png` in the release gate, and every visual
    # QA chunk fails without it.
    assert "poppler-utils" in workflow


def test_release_jobs_install_what_their_scripts_import() -> None:
    """Every release script must find its third-party imports in its own job.

    Two jobs run release tooling without installing the project. That worked
    only on the runners that happened to ship `packaging`: the Linux offline
    bundle failed on it, and `publish-draft` — the last job in the pipeline,
    after every build — would have failed the same way at the finish line.
    """
    import ast

    scripts_dir = ROOT / "scripts"
    local = {path.stem: path for path in scripts_dir.glob("*.py")}
    stdlib = set(sys.stdlib_module_names)

    def third_party_closure(entry: str) -> set[str]:
        seen: set[str] = set()
        pending = [entry]
        found: set[str] = set()
        while pending:
            name = pending.pop()
            if name in seen or name not in local:
                continue
            seen.add(name)
            tree = ast.parse(local[name].read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = {node.module.split(".")[0]}
                else:
                    continue
                for module in modules:
                    if module in local:
                        pending.append(module)
                    elif module not in stdlib and module != "__future__":
                        found.add(module)
        return found

    workflow = yaml.safe_load(_read(".github/workflows/release.yml"))

    def steps_of(job: dict) -> list[dict]:
        return [step for step in job.get("steps", []) if isinstance(step, dict)]

    for entry in ("build_offline_bundle", "finalize_release_artifacts"):
        requirements = third_party_closure(entry)
        assert requirements, f"expected scripts/{entry}.py to have third-party imports"
        running_jobs = [
            (name, job)
            for name, job in workflow["jobs"].items()
            if any(f"scripts/{entry}.py" in str(step.get("run", "")) for step in steps_of(job))
        ]
        assert running_jobs, f"no release job runs scripts/{entry}.py"
        dev_extra = {
            re.split(r"[<>=!~\[; ]", entry_spec)[0].strip().lower()
            for entry_spec in tomllib.loads(_read("pyproject.toml"))["project"][
                "optional-dependencies"
            ]["dev"]
        }
        for name, job in running_jobs:
            # Only the install commands count. A mention in a comment is not an
            # installation, which is exactly how this went unnoticed.
            installs = " ".join(
                str(step.get("run", ""))
                for step in steps_of(job)
                if "pip install" in str(step.get("run", ""))
            )
            # Installing the project's dev extra supplies everything it declares.
            via_dev_extra = '".[dev]"' in installs or "'.[dev]'" in installs
            for requirement in requirements:
                satisfied = requirement in installs or (
                    via_dev_extra and requirement.lower() in dev_extra
                )
                assert satisfied, (
                    f"job {name!r} runs scripts/{entry}.py, which needs "
                    f"{requirement!r}, but the job never installs it"
                )


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
    assert "mardas_folio.workspace" in script
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
        "mardas-folio-mark.svg",
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


def test_desktop_sidecar_packaging_metadata_is_declared() -> None:
    pyproject = _read("pyproject.toml")
    manifest = _read("MANIFEST.in")

    assert 'folio-sidecar = "mardas_folio.sidecar:main"' in pyproject
    assert 'desktop = [' in pyproject
    assert '"pyinstaller>=6.11,<7"' in pyproject
    assert "recursive-include packaging *.py *.spec" in manifest
    assert "recursive-include schemas *.json" in manifest


def test_standalone_pyinstaller_chromium_uses_analysis_data_pair() -> None:
    spec = _read("packaging/pyinstaller/mardas-sidecar.spec")

    assert 'datas.append((str(browser_root), "runtime/chromium"))' in spec
    assert "Tree(" not in spec


def test_release_gate_verifies_installed_sidecar_contract() -> None:
    script = _read("scripts/release_gate.sh")

    assert '"$venv_bin/folio-sidecar" --version' in script
    assert '"$venv_bin/folio-sidecar" --health' in script
    assert 'payload.get("protocol") != "mardas-sidecar"' in script
    assert 'payload.get("protocol_version") != 1' in script


def test_standalone_builder_discovers_only_shell_playwright_archives(
    tmp_path: Path, monkeypatch
) -> None:
    import importlib.util

    script_path = ROOT / "scripts/build_standalone_runtime.py"
    spec = importlib.util.spec_from_file_location("mardas_standalone_builder", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cache = tmp_path / "ms-playwright"
    executable_name = "chrome-headless-shell.exe" if os.name == "nt" else "chrome-headless-shell"
    executable = (
        cache / "chromium_headless_shell-1200" / "chrome-headless-shell-linux64" / executable_name
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"browser")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(cache))
    monkeypatch.setattr(module, "_browser_type_executable", lambda: None)

    assert module._playwright_browser() == executable.resolve()
