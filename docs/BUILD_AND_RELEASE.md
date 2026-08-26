# Build and release

## Local Apple Silicon build

```bash
xcode-select --install
python3 -m pip install pyinstaller
./scripts/build_macos_app.sh
```

The script refuses to overwrite an existing `dist` directory. Move the old
directory aside before rebuilding. Output:

`dist/DAW Project Cleaner.app`

## Verification

```bash
python3 -m unittest discover -v
swiftc -typecheck native/App.swift
codesign --verify --deep --strict "dist/DAW Project Cleaner.app"
spctl --assess --type execute --verbose "dist/DAW Project Cleaner.app"
```

An ad-hoc local signature passes `codesign` integrity verification but is not a
Developer ID/notarized distribution and may fail Gatekeeper assessment.

## Public release checklist

- tests pass on a clean checkout;
- source tree contains no `.cpr`, `.npr`, audio or JSON reports;
- no absolute local/server paths are present;
- quarantine/rewrite/rollback/restore and purge-refusal tests pass against temporary copies;
- exact-profile UI Apply remains limited to application-validated topologies and the pilot marker gate is tested;
- QR link and privacy statement are accurate;
- third-party notice and MIT license are included;
- version/changelog are updated;
- release archive is checksummed;
- app is signed with Developer ID and notarized for public download;
- release notes state that permanent purge is disabled;
- a second person verifies scan, Apply, DAW-open and Restore on disposable fixtures.

## Developer ID/notarization

For public distribution, replace ad-hoc signing with the maintainer's Developer
ID Application certificate, submit the ZIP/app to Apple's notary service and
staple the ticket. Credentials must never be committed.

## Reproducibility note

PyInstaller bundles can include timestamps and toolchain-specific metadata.
Record macOS, Swift, Python and PyInstaller versions with every release and
publish SHA-256 checksums.
