# Release Signing and Publication

This file describes the release credentials that are deliberately kept **outside** the Mardas MD2PDF repository.

## Security model

Three independent trust boundaries exist:

1. **Tauri updater signing** verifies that an in-app update was produced by the Mardas release process.
2. **Windows code signing** establishes the publisher identity of Windows executables/installers.
3. **macOS code signing and notarization** establish Developer ID provenance and Apple notarization for direct downloads.

Passing one boundary does not replace the others.

## Updater signing configuration

Both draft and public release runs expect:

```text
GitHub Actions secret:
  TAURI_SIGNING_PRIVATE_KEY

Optional GitHub Actions secret:
  TAURI_SIGNING_PRIVATE_KEY_PASSWORD

GitHub Actions repository/environment variable:
  MARDAS_UPDATER_PUBKEY
```

Do not add the private updater key or its password to Git. Updater signing is
independent of operating-system trust: a valid updater signature does not make an
unsigned Windows or macOS package suitable for public distribution.

A successful credentialed version-tag workflow creates a **Draft Release** only. A draft must remain unpublished until the native matrix and production signing checks from that release run have been reviewed.

## Windows public-release credentials and evidence

Configure the following external GitHub Actions values for a public run:

```text
Secrets:
  MARDAS_WINDOWS_CERTIFICATE             # base64-encoded PFX/PKCS#12
  MARDAS_WINDOWS_CERTIFICATE_PASSWORD

Repository/environment variables:
  MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT   # 40 hexadecimal characters
  MARDAS_WINDOWS_DIGEST_ALGORITHM         # sha256
  MARDAS_WINDOWS_TIMESTAMP_URL            # HTTP(S) RFC-3161 service
```

The Windows job decodes the certificate into a temporary file, imports it into
the current-user certificate store, proves that the expected certificate has a
private key and is currently valid, and deletes the file and imported certificate
after the job. No free-form signing command is accepted.

After Tauri builds the package, `verify_platform_signing.py` requires a valid,
timestamped Authenticode signature with the exact configured thumbprint on both
the normalized NSIS installer and the executable embedded in the portable ZIP.
The portable executable digest must match the separately verified signed binary.
The job then records artifact-bound signing evidence and its SHA-256 digest in the
native manifest.

The repository intentionally contains no Windows certificate, PFX/P12 file, token, private key, or certificate password.

## macOS public-release credentials and evidence

For direct-download macOS packages, use a Developer ID Application certificate. CI credentials are external.

Configure the Developer ID material below:

```text
Secrets:
  APPLE_CERTIFICATE                       # base64-encoded P12/PKCS#12
  APPLE_CERTIFICATE_PASSWORD
  KEYCHAIN_PASSWORD

Repository/environment variable:
  APPLE_SIGNING_IDENTITY                  # Developer ID Application: ... (TEAMID)
```

Configure exactly one complete notarization credential set:

```text
App Store Connect API:
  variables: APPLE_API_ISSUER, APPLE_API_KEY
  secret:    APPLE_API_KEY_P8

or Apple ID:
  secret:    APPLE_ID, APPLE_PASSWORD
  variable:  APPLE_TEAM_ID
```

The macOS job imports the certificate into a temporary keychain, requires exactly
one matching code-signing identity, validates a temporary API private key when
that method is selected, and removes all temporary signing material after the
job. Tauri performs Developer ID signing and application-bundle notarization with
those credentials. The public workflow separately submits the normalized DMG to
`notarytool`, accepts only a structured `Accepted` result, staples and validates
its ticket, and atomically refreshes the DMG digest in the native manifest.
Post-build verification requires strict `codesign` checks, the exact authority,
team identifier and CDHash, successful Gatekeeper assessment, and valid stapled
notary tickets for both the application bundle and DMG. The accepted DMG
submission identifier is bound into signing evidence. ARM64 and Intel evidence
must both pass.

Do not store `.p12`, `.cer`, `.p8`, passwords, or Apple credentials in repository
files or artifacts.

The tag workflow remains draft-only. Public publication requires actual Developer ID signing and notarization evidence from the credentialed macOS release run; configuration preflight and development/ad-hoc packages are not substitutes for that evidence.

## Linux

Linux release artifacts are verified by format, version, platform, architecture, bounded size, checksums, release provenance, and the signed Tauri update payload. Additional distribution-specific signing can be added when the project publishes through a package repository.

## Release modes and evidence gate

An updater-signed draft does not require Windows or Apple credentials. Each
native target emits explicit `not-requested`, `verified=false` evidence:

```bash
python scripts/release_preflight.py --mode draft
```

A public run is selected manually with the `workflow_dispatch` `release_mode`
input. It fails before building when any required credential set is missing or
malformed:

```bash
python scripts/release_preflight.py --mode public
```

Preflight validates only the credential contract. After every native build, the
platform verifier creates one signing-evidence file per target. The final release
gate requires exactly one Windows, two macOS and one Linux evidence file, binds
each inventory to the actual release payload digests, and rejects a public run
unless Windows and both macOS targets are verified. Linux records
`not-required`, because the current release is not published through a signed
distribution repository.

A successful tag-triggered or manually dispatched workflow still creates a
**Draft Release** only. Publishing remains an explicit maintainer action.

## Publication checklist

Do not publish a Draft Release until all applicable checks are true:

- tag equals `v<project-version>`;
- Windows/macOS/Linux native CI jobs are green;
- `RELEASE-MANIFEST.json` verifies;
- `CHECKSUMS.sha256` verifies;
- SBOM and attestations exist;
- `latest.json` verifies and references the same tag;
- updater signatures exist for every supported update target;
- Windows evidence proves the intended Authenticode publisher and timestamp;
- both macOS evidence files prove Developer ID signing, Gatekeeper acceptance,
  and stapled notarization;
- release notes match the changelog;
- known limitations have been reviewed;
- install/upgrade smoke tests are green on clean machines.

Publishing is always an explicit maintainer action.
