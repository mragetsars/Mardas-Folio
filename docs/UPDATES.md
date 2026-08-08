# Desktop Update Readiness

Mardas Studio uses the Tauri v2 updater trust model. Update installation is not considered production-ready until the maintainer creates and safely stores a long-lived updater signing key and the application contains the matching public key.

## Security boundary

Updater signatures are mandatory. The private signing key must stay outside the repository and outside ordinary build artifacts. The public key may be distributed with the application.

Recommended secret names for CI:

```text
TAURI_SIGNING_PRIVATE_KEY
TAURI_SIGNING_PRIVATE_KEY_PASSWORD
```

Do not store these values in `.env`, source files, test fixtures, support bundles, or generated release metadata.

Generate the key pair on a trusted maintainer machine using the Tauri CLI and make multiple secure backups of the private key. Losing the updater private key can prevent safe updates for already-installed clients.

## Static update metadata

`scripts/generate_update_manifest.py` creates and verifies the static multi-platform `latest.json` format used by Tauri. It intentionally requires signature **contents**, not signature URLs.

Example after signed updater bundles exist:

```bash
python scripts/generate_update_manifest.py   --version X.Y.Z   --platform "windows-x86_64=https://github.com/.../windows-update.zip,windows-update.zip.sig"   --platform "linux-x86_64=https://github.com/.../Mardas-Studio.AppImage,Mardas-Studio.AppImage.sig"   --platform "darwin-aarch64=https://github.com/.../Mardas-Studio.app.tar.gz,Mardas-Studio.app.tar.gz.sig"   --output latest.json
```

Verify before publication:

```bash
python scripts/generate_update_manifest.py   --verify latest.json   --expected-version X.Y.Z
```

The generator rejects HTTP URLs, embedded URL credentials, duplicate/unsupported targets, empty signatures, invalid semantic versions, and malformed publication dates.

## Activation sequence

Do not enable automatic updates merely by adding a placeholder public key. Production activation requires all of the following:

1. Generate the maintainer updater signing key.
2. Store the private key and optional password as protected release secrets.
3. Add only the public key to the application updater configuration.
4. Enable Tauri updater artifact generation.
5. Build signed updater artifacts on every supported target.
6. Publish a verified HTTPS `latest.json`.
7. Add UI for check/download/install/restart with clear user consent.
8. Test update, interrupted update, signature failure, no-update, downgrade policy, and rollback/recovery scenarios on clean machines.

Until these steps are completed, the repository is **update-ready**, not auto-update-enabled.
