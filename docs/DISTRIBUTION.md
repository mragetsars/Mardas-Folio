# Native Desktop Distribution

Mardas Folio release engineering builds the Python publishing engine and the native desktop shell as one verified product. End users should install a native package; they should not need Python, Node.js, Rust, Git, Playwright, or a separately installed Chromium renderer.

## Release artifact contract

A complete public desktop release must contain native artifacts for all supported desktop platforms:

```text
Mardas-Folio-X.Y.Z-windows-x86_64-setup.exe
Mardas-Folio-X.Y.Z-windows-x86_64-portable.zip
Mardas-Folio-X.Y.Z-macos-arm64.dmg
Mardas-Folio-X.Y.Z-macos-x86_64.dmg
Mardas-Folio-X.Y.Z-linux-x86_64.AppImage
Mardas-Folio-X.Y.Z-linux-x86_64.deb
```

Platform CI is authoritative. PyInstaller and Tauri are not treated as cross-compilers: the frozen sidecar runtime and native package must be built and smoke-tested on the target operating system. Source-level or portable tests alone are not evidence that those native jobs completed for a particular release.

The release manifest records the normalized file name, artifact kind, size, SHA-256 digest, platform, and architecture. Release finalization fails if Windows, macOS, or Linux native coverage is missing.

## Supported native targets

| Platform | Architecture | Release-tested minimum |
|---|---|---|
| Windows | x86-64 | Windows 11 or Windows Server 2019 |
| macOS | ARM64 and x86-64 | macOS 14 (Sonoma) |
| Linux | x86-64 | Ubuntu 22.04 |

These minimums follow the pinned Playwright/Chromium renderer and the actual
native release runners. AppImage may run on other compatible glibc-based Linux
distributions, but those systems are outside the published acceptance matrix.

## Windows

The primary Windows distribution is the NSIS Setup executable. Its Tauri configuration uses the WebView2 offline installer so a normal installation does not require a network fetch for the UI runtime. The Mardas rendering sidecar and pinned Chromium headless shell are bundled separately as application resources.

The portable ZIP contains the same Mardas sidecar runtime and rendering browser but does not bundle WebView2. It is a secondary convenience artifact for systems that already provide WebView2; Setup remains the recommended Windows download.

In a public release run, Tauri signs with the externally provisioned certificate
thumbprint. The release verifier requires valid timestamped Authenticode on the
NSIS installer and packaged executable, and proves that the portable ZIP contains
that same verified binary.

## macOS

The release workflow is configured to produce one DMG per supported architecture, with ARM64 and Intel artifacts built on separate macOS runners. Source configuration does not embed a production signing identity: local/development packages may be unsigned or use toolchain-provided ad-hoc behavior, and are not public-release evidence.

A public stable macOS release must be signed and notarized with maintainer-owned Apple credentials. Those credentials and private keys must never be committed to this repository.

The public workflow imports the Developer ID certificate into a temporary
keychain and uses exactly one notarization credential method. After Tauri
notarizes the application, an explicit accepted-only `notarytool` step submits
and staples the normalized DMG and refreshes its manifest digest. Both
architecture jobs must then prove strict code signatures, the expected
identity/team, Gatekeeper acceptance, and stapled notary tickets for the
application and DMG.

## Linux

Linux CI builds on Ubuntu 22.04 and emits both AppImage and Debian packages. Building on the older supported CI baseline reduces the risk of producing an AppImage that requires a newer glibc than common target systems.

The AppImage is the portable Linux download. The `.deb` package is the conventional Debian/Ubuntu installation path.

## Build locally on the target OS

Build a verified standalone runtime first:

```bash
python -m pip install -e '.[desktop]'
python -m playwright install chromium --only-shell
python scripts/build_standalone_runtime.py --clean
python scripts/verify_standalone_runtime.py   build/standalone-runtime/Mardas-Folio-X.Y.Z-runtime-<platform>-<arch>   --render
```

Then build native artifacts:

```bash
python scripts/build_native_desktop.py   --runtime build/standalone-runtime/Mardas-Folio-X.Y.Z-runtime-<platform>-<arch>   --clean
```

Verify an individual normalized artifact:

```bash
python scripts/verify_native_desktop.py   build/desktop-native/Mardas-Folio-X.Y.Z-<platform>-<arch>.<suffix>   --version X.Y.Z
```

The builder verifies the deterministic offline frontend, including the checked-in CodeMirror 6 bundle, and the complete schema-v2 standalone-runtime file/symlink inventory before invoking Tauri.

## Signed updater payloads

Version 2.0.0 can ask Tauri to create signed updater artifacts in addition to the normal installers:

```bash
python scripts/build_native_desktop.py   --runtime <verified-runtime>   --create-updater-artifacts   --clean
```

The updater private key is supplied only through the release environment. The normalized detached signatures and macOS updater archives are verified with the same native-artifact boundary before entering release metadata. See `docs/UPDATES.md` for the trust model and `latest.json` assembly.

## GitHub Release boundary

A version tag can stage a **Draft GitHub Release** only when the updater credentials are provisioned and the native matrix, signed updater assets, checksums, SBOM, release manifest, and attestations complete successfully. The workflow refuses to overwrite a release that has already been published.

A draft is not permission to publish and does not itself prove code signing or notarization. A manually dispatched public run fails closed unless the final evidence set contains one verified Windows target, two verified macOS targets, and the expected Linux target. Publication remains a maintainer gate and also requires installer smoke results, checksums, update metadata, known limitations, and release-note review.

Code-signing and updater private keys are external release secrets. Do not add them to source, test fixtures, support bundles, `.env` files, or GitHub artifacts.
