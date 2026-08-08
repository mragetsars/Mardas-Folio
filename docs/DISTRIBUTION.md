# Native Desktop Distribution

Mardas Studio release engineering builds the Python publishing engine and the native desktop shell as one verified product. End users should install a native package; they should not need Python, Node.js, Rust, Git, Playwright, or a separately installed Chromium renderer.

## Release artifact contract

A complete public desktop release must contain native artifacts for all supported desktop platforms:

```text
Mardas-Studio-X.Y.Z-windows-x86_64-setup.exe
Mardas-Studio-X.Y.Z-windows-x86_64-portable.zip
Mardas-Studio-X.Y.Z-macos-arm64.dmg
Mardas-Studio-X.Y.Z-macos-x86_64.dmg
Mardas-Studio-X.Y.Z-linux-x86_64.AppImage
Mardas-Studio-X.Y.Z-linux-x86_64.deb
```

Platform CI is authoritative. PyInstaller and Tauri are not treated as cross-compilers: the frozen sidecar runtime and native package are built and smoke-tested on the target operating system.

The release manifest records the normalized file name, artifact kind, size, SHA-256 digest, platform, and architecture. Release finalization fails if Windows, macOS, or Linux native coverage is missing.

## Windows

The primary Windows distribution is the NSIS Setup executable. Its Tauri configuration uses the WebView2 offline installer so a normal installation does not require a network fetch for the UI runtime. The Mardas rendering sidecar and pinned Chromium headless shell are bundled separately as application resources.

The portable ZIP contains the same Mardas sidecar runtime and rendering browser but does not bundle WebView2. It is a secondary convenience artifact for systems that already provide WebView2; Setup remains the recommended Windows download.

## macOS

macOS produces one DMG per supported architecture. CI builds ARM64 and Intel artifacts on separate runners. The source configuration uses an ad-hoc signing identity for unsigned development artifacts so local/CI packaging can be exercised without private Apple credentials.

A public stable macOS release must be signed and notarized with maintainer-owned Apple credentials. Those credentials and private keys must never be committed to this repository.

## Linux

Linux CI builds on Ubuntu 22.04 and emits both AppImage and Debian packages. Building on the older supported CI baseline reduces the risk of producing an AppImage that requires a newer glibc than common target systems.

The AppImage is the portable Linux download. The `.deb` package is the conventional Debian/Ubuntu installation path.

## Build locally on the target OS

Build a verified standalone runtime first:

```bash
python -m pip install -e '.[desktop]'
python -m playwright install chromium --only-shell
python scripts/build_standalone_runtime.py --clean
python scripts/verify_standalone_runtime.py   build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-<platform>-<arch>   --render
```

Then build native artifacts:

```bash
python scripts/build_native_desktop.py   --runtime build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-<platform>-<arch>   --clean
```

Verify an individual normalized artifact:

```bash
python scripts/verify_native_desktop.py   build/desktop-native/Mardas-Studio-X.Y.Z-<platform>-<arch>.<suffix>   --version X.Y.Z
```

The builder verifies the deterministic frontend and the complete standalone-runtime hash inventory before invoking Tauri.

## Signed updater payloads

Version 1.30.0 can ask Tauri to create signed updater artifacts in addition to the normal installers:

```bash
python scripts/build_native_desktop.py   --runtime <verified-runtime>   --create-updater-artifacts   --clean
```

The updater private key is supplied only through the release environment. The normalized detached signatures and macOS updater archives are verified with the same native-artifact boundary before entering release metadata. See `docs/UPDATES.md` for the trust model and `latest.json` assembly.

## GitHub Release boundary

A version tag now stages a **Draft GitHub Release** only after the verified native matrix, signed updater assets, checksums, SBOM, release manifest, and attestations have completed. The workflow refuses to overwrite a release that has already been published.

A draft is not permission to publish. Public release remains a maintainer gate and requires review of the native matrix, signing/notarization state, checksums, update metadata, known limitations, and release notes.

Code-signing and updater private keys are external release secrets. Do not add them to source, test fixtures, support bundles, `.env` files, or GitHub artifacts.
