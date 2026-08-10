# Release Checklist

Use this checklist when preparing a tagged Mardas Folio release.

## Version bump

The version is declared in six places. All six must agree, because the desktop
package, the Rust crate and the Python distribution are built from different
files and a mismatch is only caught late, during bundling:

- `pyproject.toml` — Python distribution.
- `src/mardas_md2pdf/__init__.py` — `__version__`, which the engine reports over the sidecar protocol.
- `apps/desktop/package.json` and `apps/desktop/package-lock.json` — desktop workspace.
- `apps/desktop/src-tauri/tauri.conf.json` — bundle version used for installer and update metadata.
- `apps/desktop/src-tauri/Cargo.toml` — Rust crate.

Then update the documentation:

- Update the README version badge and any sample paths that carry the version.
- Update guide front matter and the version-history section in `docs/guides/GUIDE.en.md` and `docs/guides/GUIDE.fa.md`.
- Update `docs/CHANGELOG.md` with the release date and a concise summary.

`tests/test_desktop_app.py` and `tests/test_documentation_integrity.py` hold the
declared versions against `__version__`, so a partial bump fails the suite.

## Quality gates

Run the local checks before tagging. The check helper keeps pytest isolated from unrelated third-party plugins unless `MARDAS_ALLOW_PYTEST_PLUGINS=1` is explicitly set:

```bash
./scripts/check.sh
./scripts/check_critical_coverage.sh
./scripts/security_audit.sh
python -m pytest -q tests/test_project_config.py tests/test_book_mode.py tests/test_cross_references.py tests/test_citations.py tests/test_studio_project_workspace.py
```

For a full release verification, use the consolidated release gate:

```bash
./scripts/release_gate.sh
```

The gate runs the complete release contract: Ruff, scoped Pyright, critical branch coverage, installed-dependency audit, and pytest, real Chromium render smoke, guide regeneration, PDF preflight, representative or full Visual QA, deterministic wheel/sdist construction, clean-wheel installation, console-entry-point checks, packaged-asset checks, a clean-wheel multi-file Book Mode build with all four numbered reference-object kinds, offline citations, verified reference/bibliography PDF destinations, an installed-wheel Studio Project Workspace hash-save check, a Chromium Problems Panel/Project Explorer audit, and distribution checksums. The tag workflow invokes this same gate instead of maintaining a weaker parallel command list.

For targeted diagnosis, the underlying helpers remain available individually:

```bash
./scripts/check.sh
./scripts/check_types.sh
./scripts/check_critical_coverage.sh
./scripts/security_audit.sh
./scripts/build_examples.sh
./scripts/build_dist.sh
./scripts/clean_workspace.sh
```

A tagged release must still use `./scripts/release_gate.sh`; the individual commands are not a substitute for the consolidated gate.

For exhaustive local visual review, opt in to the full chunked Visual QA matrix:

```bash
MARDAS_RELEASE_VISUAL_QA=1 ./scripts/release_gate.sh
```

When a release runner is slow, use `MARDAS_TIMEOUT_MS` for Chromium's page timeout and `MARDAS_RENDER_SMOKE_TIMEOUT` for the outer `./scripts/check.sh` smoke-render command timeout.

For a performance-affecting release, preserve a benchmark report under `build/performance/` and compare it with the recorded baseline using identical profiles and environment details:

```bash
python scripts/benchmark_large_documents.py \
  --profiles small,pages50,pages250,editor-loop \
  --mode both \
  --repeats 3 \
  --output-dir build/performance
```

The release gate verifies persistent Chromium reuse from the installed wheel, thread-affine queue sessions, and packaged `render_pool.py`/`studio_jobs.py`. A performance claim additionally requires reported before/after wall time, page-count equivalence, output-size checks, and peak-memory context. Treat regressions greater than 10% on a representative profile as release-blocking until explained.

For a targeted Studio Project Workspace review, run:

```bash
python scripts/audit_studio_visual.py \
  --project path/to/book-project \
  --output-dir build/studio-project-audit \
  --clean
```

Confirm the Project Explorer, Problems Panel, active project path, renderer-backed preview, Save/Validate controls, and Book Preview/Export controls are present. Also test an external file modification and confirm Studio reports a conflict instead of overwriting it.

Use `./scripts/clean_workspace.sh --patches` after local patch application if temporary patch bundles were unpacked into the repository root.

Semantic visual contracts are enforced with `scripts/check_visual_contracts.py`; they reject incomplete manifests, blank/implausibly small rasters, and missing Studio interaction checks while avoiding machine-specific hash baselines. The release gate writes PDF preflight data to `build/release/pdf-preflight.json` and one-case Visual QA smoke artifacts to `build/release/visual-qa-smoke/` unless `MARDAS_RELEASE_VISUAL_QA=1` is set. The full visual matrix is chunked and resumable: rerun `python scripts/run_visual_qa_matrix.py --output-dir build/release/visual-qa --render-png --resume` to skip chunks whose manifests are already complete. The matrix summary records active-chunk heartbeat data so a slow runner can be inspected while it is still running.

Open the generated PDFs and visually check the cover, table of contents, generated reference lists, numbered figures/tables/equations/listings, cross-reference links, grouped/narrative citations, the generated bibliography, page numbers, code blocks, formulas, Mermaid diagrams, local images, wide tables, blocked-image placeholders, watermarks, and footnotes. When changing appearance CSS or palette behavior, also run `python scripts/audit_appearance_matrix.py --output-dir build/appearance-audit --render-png --resume` and review the full style/palette/mode matrix. Guide builds and Python distributions honor a deterministic `SOURCE_DATE_EPOCH`; the distribution helper additionally normalizes source-archive metadata so repeated builds from one commit are byte-identical. In offline or pre-provisioned release environments, `MARDAS_BUILD_NO_ISOLATION=1 ./scripts/build_dist.sh (falls back to the installed `setuptools.build_meta` backend when the PyPA `build` frontend is unavailable)` reuses the current environment instead of creating an isolated build environment.

## Cross-platform distribution and provenance

The supported release pipeline has three distinct contracts:

1. `CI` runs the complete pytest suite across Linux, Windows, and macOS, with Python compatibility coverage from 3.10 through 3.13.
2. A wheel-render smoke installs Chromium and renders a Unicode-path mixed RTL/LTR PDF from the built wheel on all three operating systems.
3. `Release Artifacts` builds the deterministic core distributions, platform-specific offline Python bundles, the self-contained Windows sidecar runtime, an SPDX 2.3 SBOM, a release manifest, and signed GitHub attestations.

The local release gate writes the following core files under `dist/`:

```text
mardas_md2pdf-X.Y.Z-py3-none-any.whl
mardas_md2pdf-X.Y.Z.tar.gz
mardas-md2pdf-X.Y.Z.spdx.json
RELEASE-MANIFEST.json
CHECKSUMS.sha256
```

Generate or verify those files directly when diagnosing a release runner:

```bash
python scripts/generate_sbom.py \
  --python path/to/clean-venv/bin/python \
  --artifact dist/mardas_md2pdf-X.Y.Z-py3-none-any.whl \
  --artifact dist/mardas_md2pdf-X.Y.Z.tar.gz \
  --output dist/mardas-md2pdf-X.Y.Z.spdx.json

python scripts/finalize_release_artifacts.py \
  --artifact-dir dist \
  --version X.Y.Z \
  --require-sbom
```

Every release manifest records exact file sizes and SHA-256 digests. Verification rejects extra files, missing files, path traversal, symlink artifacts, checksum mismatches, duplicate inventory entries, malformed SPDX data, or an unexpected project version.


### Standalone sidecar runtime

Build the portable runtime only on the target operating system. The Windows release job installs the Playwright Chromium headless shell, freezes the sidecar with PyInstaller `onedir`, copies the complete browser archive, writes a per-file SHA-256 manifest, and performs a Unicode-path PDF render from the frozen executable:

```bash
python -m pip install -e '.[desktop]'
python -m playwright install chromium --only-shell
python scripts/build_standalone_runtime.py --clean
python scripts/verify_standalone_runtime.py \
  build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-windows-x86_64 \
  --render
```

A release standalone runtime must include Chromium and pass `verify_standalone_runtime`. Runtime manifest schema v2 records regular files and safe relative symbolic links; the verifier rejects escaping, dangling, cyclic, undeclared, or mismatched links and continues to accept schema-v1 regular-file manifests. `--allow-missing-chromium` is restricted to protocol/build diagnostics and does not satisfy the release contract. `finalize_release_artifacts.py` classifies this ZIP separately from legacy offline wheel bundles and verifies its internal manifest before checksums and attestations are finalized.

The tag workflow creates one offline Python wheel bundle per runner platform with `scripts/build_offline_bundle.py`. Each archive contains an offline wheelhouse, deterministic bundle metadata, an installer, and its own checksum list. It does **not** contain Chromium or an embedded Python runtime. Test the bundle after extraction with:

```bash
python install.py --target mardas-md2pdf-venv
mardas-md2pdf-venv/bin/mrs-md2pdf --version
```

GitHub-hosted release jobs use `actions/attest` to create signed SLSA build-provenance and SPDX SBOM attestations. Verify an artifact after download:

```bash
gh attestation verify artifact-name --repo mragetsars/Mardas-MD2PDF
```

The workflow uploads the manifest-governed release payload and the generated Sigstore bundles as separate artifacts. The attestation artifact has its own checksum inventory because signatures are produced only after the release payload is finalized. The workflow does not create or publish a GitHub Release automatically; publishing remains an explicit maintainer action.

## Commit style

Keep commit subjects short and conventional. Existing history uses subjects such as:

```text
feat: add PDF export progress feedback
fix: harden display math and pagebreak directives
docs: refresh guide PDF examples
chore: bump version to 1.5.1
```

Prefer one concern per commit so generated patches stay reviewable.

## Tagging

After the final commit is in place and CI is green:

```bash
git tag vX.Y.Z
git push origin master --tags
```

The `Release Artifacts` workflow runs on `v*` tags and uploads the Python distributions and regenerated guide PDFs. Create the GitHub Release from the tag, copy the matching `docs/CHANGELOG.md` entry into the release notes, and attach the workflow artifacts.


## Maintenance docs

See [`docs/MAINTENANCE.md`](./MAINTENANCE.md) for the daily check, example-generation, distribution-build, and patch-set workflow.

## Accessibility and archival-readiness release checks

Before tagging a release that changes rendering, metadata, fonts, themes, images, tables, or navigation, build representative documents with `--quality-profile strict-publication` and retain the JSON quality report alongside the release evidence. Then run:

```bash
mrs-md2pdf audit-accessibility docs/guides/GUIDE.en.md --format json --fail-on error
mrs-md2pdf audit-accessibility docs/guides/GUIDE.fa.md --format json --fail-on error
mrs-md2pdf audit-pdf examples/GUIDE.en.pdf --profile all --format json --fail-on never
mrs-md2pdf audit-pdf examples/GUIDE.fa.pdf --profile all --format json --fail-on never
```

The clean-wheel release gate must execute `audit-accessibility`, `audit-book-accessibility`, and `audit-pdf`. Confirm that generated PDFs declare language and contain XMP metadata, all ordinary fonts are embedded with usable ToUnicode mappings where applicable, and no unexpected JavaScript or attachments appear. An untagged Chromium PDF or missing PDF/A output intent must remain an explicit readiness limitation; the release notes must not claim PDF/UA or PDF/A conformance without independent validator evidence.

## Native Windows desktop installer

Build the standalone Windows runtime first, then build the native NSIS installer from the same verified directory:

```powershell
python scripts/build_desktop_app.py `
  --runtime build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-windows-x86_64 `
  --clean
python scripts/verify_desktop_installer.py `
  build/desktop/Mardas-Folio-X.Y.Z-windows-x86_64-setup.exe `
  --version X.Y.Z
```

The tag workflow downloads the target-runner-tested standalone runtime, stages it as a Tauri resource, verifies the locked and locally bundled CodeMirror 6 frontend, compiles the Tauri shell, and uploads the NSIS setup executable. Finalization requires at least one `desktop-installer`, verifies its versioned filename, bounded size, and Windows PE header, then includes it in checksums and attestations. In `public` mode the Windows runner additionally proves the exact Authenticode signer, timestamp, and portable executable digest before the artifact may enter finalization. Source-level checks alone do not establish Authenticode signing. A release must never substitute an unverified runtime directory or a locally installed browser.

## Cross-platform native desktop release

Version 1.29.0 treats native desktop packages as first-class release artifacts. CI builds the frozen Python/Chromium runtime on the same target platform as the Tauri package, then normalizes and verifies the resulting files with `scripts/build_native_desktop.py` and `scripts/verify_native_desktop.py`.

A complete native release must include Windows, macOS, and Linux coverage. Windows produces the recommended NSIS Setup plus a portable ZIP; macOS produces architecture-specific DMGs; Linux produces AppImage and Debian packages. See `docs/DISTRIBUTION.md` for the exact artifact contract.

The Windows Setup configuration embeds the WebView2 offline installer. The portable ZIP intentionally does not bundle WebView2 and is secondary to Setup.

The release finalizer can enforce platform coverage:

```bash
python scripts/finalize_release_artifacts.py   --artifact-dir build/release   --version X.Y.Z   --source-revision "$GITHUB_SHA"   --require-sbom   --minimum-native-desktop-count 5   --require-desktop-platform windows   --require-desktop-platform macos   --require-desktop-platform linux
```

## Signed updater and draft-release boundary

Version 2.0.0 retains the end-to-end updater workflow but keeps it secret-driven. Development builds do not contact an update service unless a maintainer-controlled public key is embedded at build time.

Before a tag workflow can build signed updater artifacts, configure the external release secret/variable boundary described in `docs/UPDATES.md`. The draft preflight is:

```bash
python scripts/release_preflight.py --mode draft
```

Platform jobs call `scripts/build_native_desktop.py --create-updater-artifacts`, and the finalization job verifies those payloads before assembling the multi-platform `latest.json` with `scripts/assemble_signed_updates.py`.

Final release verification requires the update manifest:

```bash
python scripts/finalize_release_artifacts.py   --artifact-dir build/release   --version X.Y.Z   --source-revision "$GITHUB_SHA"   --require-sbom   --minimum-native-desktop-count 5   --require-desktop-platform windows   --require-desktop-platform macos   --require-desktop-platform linux   --require-update-manifest
```

For a version tag, the workflow can create or refresh a **Draft GitHub Release** only after the credential-dependent preflight and required native jobs succeed. It never automatically publishes the release and refuses to replace an already-published tag. Local portable tests do not substitute for target-platform installer smoke, Windows signature inspection, or macOS Developer ID/notarization evidence.

Start a manually dispatched `public` release run and review its preflight:

```bash
python scripts/release_preflight.py --mode public
```

Preflight is followed by fail-closed target verification. Finalization requires exactly one Windows, two macOS, and one Linux signing-evidence file; Windows and both macOS targets must carry verified artifact-bound operating-system trust evidence. Updater signatures do not substitute for Windows publisher signing or macOS Developer ID signing/notarization. See `docs/RELEASE_SIGNING.md` and `docs/DISTRIBUTION.md`.

## Release signing operations

See `docs/RELEASE_SIGNING.md` before provisioning updater, Windows, or Apple credentials and before publishing a draft release.
