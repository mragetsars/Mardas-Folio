# Signed Desktop Updates

Mardas Folio 2.0.0 implements the application-side and release-side Tauri v2 updater flow, but update capability is **secret-driven**. Development builds and ordinary source builds remain offline and report updates as unavailable unless a maintainer-controlled public key is embedded at build time.

## Trust boundary

Tauri updater signatures are mandatory. The long-lived updater private key must stay outside:

- source control;
- `.env` files committed to Git;
- test fixtures;
- support bundles;
- release metadata;
- release artifacts other than the detached signatures generated from it.

GitHub release secrets/variables used by the tag workflow:

```text
Secret:   TAURI_SIGNING_PRIVATE_KEY
Secret:   TAURI_SIGNING_PRIVATE_KEY_PASSWORD   # only when the key is encrypted
Variable: MARDAS_UPDATER_PUBKEY
```

The application embeds only the public key and an HTTPS endpoint. The default stable feed is:

```text
https://github.com/mragetsars/Mardas-Folio/releases/latest/download/latest.json
```

`release_preflight.py` rejects an HTTP endpoint, embedded credentials, or fragments.

## Generate the updater key once

This key is required for **every** release, including an unsigned draft: the
preflight marks `updater_private_key` and `updater_public_key` as blocking in
both `draft` and `public` mode, so the tag workflow stops at its first job
without them. It is unrelated to Windows Authenticode and Apple Developer ID
signing, which are free to remain absent until a public release.

Run the key generation on a trusted maintainer machine, with the same Tauri v2
toolchain used for release engineering — the repository pins `tauri-cli 2.11.4`:

```bash
cargo install tauri-cli --version 2.11.4 --locked
cargo tauri signer generate -w ~/.tauri/mardas-folio.key
```

The command prompts for a password, which may be empty, and writes two files:

```text
~/.tauri/mardas-folio.key       # private key — never leaves the maintainer machine
~/.tauri/mardas-folio.key.pub   # public key — embedded in every desktop build
```

Store multiple secure backups of the private key and its password. Losing this
key can prevent already-installed clients from accepting future updates: an
update is only installed when its detached signature verifies against the public
key already embedded in the installed application, so a replacement key is
rejected by every client built before it.

Never paste the private key into an issue, release note, support bundle, source
file, or chat transcript.

After creating the key, register it on GitHub under
**Settings → Secrets and variables → Actions**:

1. store the *contents* of `mardas-folio.key` as the secret `TAURI_SIGNING_PRIVATE_KEY`;
2. store its password, when one was set, as the secret `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`;
3. store the *contents* of `mardas-folio.key.pub` as the **variable** — the
   Variables tab, not Secrets — `MARDAS_UPDATER_PUBKEY`.

The public key belongs in a variable rather than a secret because it is embedded
in every published binary and is not confidential; masking it in logs would only
obscure the build.

Before creating a tag, the draft release preflight can be exercised locally against the generated key files, which keeps the values off the command line and out of shell history:

```bash
TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/mardas-folio.key)" \
MARDAS_UPDATER_PUBKEY="$(cat ~/.tauri/mardas-folio.key.pub)" \
python scripts/release_preflight.py --mode draft
```

The preflight reports names and readiness only; it does not print secret contents. It exits 0 when the updater key is configured and 2 when it is missing, in `draft` mode as much as in `public`.

## Signed native updater artifacts

Release builds call:

```bash
python scripts/build_native_desktop.py \
  --runtime <verified-runtime> \
  --create-updater-artifacts \
  --clean
```

Tauri creates signatures with `TAURI_SIGNING_PRIVATE_KEY`. Mardas normalizes and verifies:

```text
Windows:
Mardas-Folio-X.Y.Z-windows-x86_64-setup.exe
Mardas-Folio-X.Y.Z-windows-x86_64-setup.exe.sig

Linux:
Mardas-Folio-X.Y.Z-linux-x86_64.AppImage
Mardas-Folio-X.Y.Z-linux-x86_64.AppImage.sig

macOS:
Mardas-Folio-X.Y.Z-macos-arm64-updater.tar.gz
Mardas-Folio-X.Y.Z-macos-arm64-updater.tar.gz.sig
Mardas-Folio-X.Y.Z-macos-x86_64-updater.tar.gz
Mardas-Folio-X.Y.Z-macos-x86_64-updater.tar.gz.sig
```

The ordinary DMG/DEB/portable artifacts are still produced for direct installation. Updater payloads are separate release assets.

## Assemble `latest.json`

After all required native jobs finish:

```bash
python scripts/extract_release_notes.py \
  --version X.Y.Z \
  --output build/RELEASE-NOTES.md

python scripts/assemble_signed_updates.py \
  --artifact-dir build/release \
  --version X.Y.Z \
  --repository mragetsars/Mardas-Folio \
  --tag vX.Y.Z \
  --notes-file build/RELEASE-NOTES.md
```

The assembler verifies each native payload and detached signature before creating `latest.json`. The manifest generator rejects insecure URLs, credentials in URLs, unknown/duplicate targets, empty signatures, invalid versions, and malformed publication dates.

Verify independently:

```bash
python scripts/generate_update_manifest.py \
  --verify build/release/latest.json \
  --expected-version X.Y.Z
```

## Application behavior

The **Settings → Software Updates** panel is intentionally manual:

1. the application reads its embedded update configuration;
2. if no public key was embedded, the UI clearly reports that updates are unavailable for this build;
3. the user presses **Check for updates**;
4. the native Rust boundary fetches the HTTPS metadata with a bounded timeout;
5. when an update is available, the user explicitly chooses **Install update**;
6. Tauri verifies the detached updater signature before installation.

The frontend does not fetch release metadata directly and has no updater private key.

On Windows, the installer step exits the application as required by the Tauri updater. macOS/Linux installs can complete before the user restarts the application.

## GitHub Draft Release

A credentialed, successful tag workflow stages a **Draft Release**, never an automatically published release. The workflow:

1. builds the verified core and platform artifacts;
2. builds signed updater payloads;
3. assembles `latest.json`;
4. validates the release manifest and checksums;
5. attests the finalized artifacts;
6. creates or refreshes a draft GitHub Release.

If the same tag already exists as a published release, the workflow refuses to overwrite it.

Draft releases are intentionally excluded from the stable `releases/latest` updater endpoint. Publishing is a maintainer decision after platform-signing and final acceptance checks.

## Public-release gate

Updater signatures protect application-update integrity, but they do **not** replace operating-system publisher trust.

Before a public stable release, verify:

```bash
python scripts/release_preflight.py --mode public
```

A production release still needs:

- verified, timestamped Windows Authenticode evidence;
- verified macOS Developer ID and Gatekeeper evidence for both architectures;
- valid stapled notarization tickets for both macOS application bundles and DMGs;
- green native Windows/macOS/Linux build and smoke jobs;
- final release-manifest/checksum/attestation review.

The `public` target-platform jobs create artifact-bound evidence and finalization rejects missing, mismatched, unsigned, or unnotarized targets. Keep the GitHub Release in Draft state until that evidence and the remaining acceptance checks have been reviewed. Repository tests and preflight output describe the contract; only the credentialed native run proves a particular artifact.
