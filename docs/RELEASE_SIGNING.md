# Release Signing and Publication

This file describes the release credentials that are deliberately kept **outside** the Mardas MD2PDF repository.

## Security model

Three independent trust boundaries exist:

1. **Tauri updater signing** verifies that an in-app update was produced by the Mardas release process.
2. **Windows code signing** establishes the publisher identity of Windows executables/installers.
3. **macOS code signing and notarization** establish Developer ID provenance and Apple notarization for direct downloads.

Passing one boundary does not replace the others.

## GitHub release configuration

The signed-updater draft workflow expects:

```text
GitHub Actions secret:
  TAURI_SIGNING_PRIVATE_KEY

Optional GitHub Actions secret:
  TAURI_SIGNING_PRIVATE_KEY_PASSWORD

GitHub Actions repository/environment variable:
  MARDAS_UPDATER_PUBKEY
```

Do not add the private updater key or its password to Git.

The version tag workflow creates a **Draft Release** only. A draft must remain unpublished until the native matrix and production signing checks have been reviewed.

## Windows public-release readiness

Mardas release preflight recognizes either:

```text
MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT
```

or a maintainer-controlled signing integration represented by:

```text
MARDAS_WINDOWS_SIGN_COMMAND
```

as credential/configuration readiness. This is not evidence that a particular artifact is signed. The actual Windows package must still be built on the Windows release runner and its signature must be inspected before publication.

The repository intentionally contains no Windows certificate, PFX/P12 file, token, private key, or certificate password.

## macOS public-release readiness

For direct-download macOS packages, use a Developer ID Application certificate. CI credentials are external.

The preflight accepts a configured signing identity or CI certificate material and requires one complete notarization credential set:

```text
Developer ID / certificate:
  APPLE_SIGNING_IDENTITY
  or APPLE_CERTIFICATE + APPLE_CERTIFICATE_PASSWORD

Notarization, App Store Connect API:
  APPLE_API_ISSUER
  APPLE_API_KEY
  APPLE_API_KEY_PATH

or Apple ID:
  APPLE_ID
  APPLE_PASSWORD
  APPLE_TEAM_ID
```

Do not store `.p12`, `.cer`, `.p8`, passwords, or Apple credentials in repository files or artifacts.

The Phase 27 workflow remains draft-only because the current platform configuration still permits development/ad-hoc packaging. Public publication requires actual Developer ID signing and notarization evidence from the release run.

## Linux

Linux release artifacts are verified by format, version, platform, architecture, bounded size, checksums, release provenance, and the signed Tauri update payload. Additional distribution-specific signing can be added when the project publishes through a package repository.

## Preflight

Updater-signed draft:

```bash
python scripts/release_preflight.py --mode draft
```

Public-release credential readiness:

```bash
python scripts/release_preflight.py --mode public
```

The public mode is a configuration preflight, not a substitute for artifact signature verification.

## Publication checklist

Do not publish a Draft Release until all applicable checks are true:

- tag equals `v<project-version>`;
- Windows/macOS/Linux native CI jobs are green;
- `RELEASE-MANIFEST.json` verifies;
- `CHECKSUMS.sha256` verifies;
- SBOM and attestations exist;
- `latest.json` verifies and references the same tag;
- updater signatures exist for every supported update target;
- Windows public artifact has the intended publisher signature;
- both macOS architectures are Developer ID signed and notarized;
- release notes match the changelog;
- known limitations have been reviewed;
- install/upgrade smoke tests are green on clean machines.

Publishing is always an explicit maintainer action.
