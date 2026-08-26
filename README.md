# DAW Project Cleaner

DAW Project Cleaner is an independent, local, safety-first macOS utility that
inventories Cubase and Nuendo project archives. It finds `.cpr` and `.npr`
projects recursively, identifies their embedded writer/version, reports media
references and estimates how much disk space is associated with media that
appears only on the project-pool side.

Version 0.11.0 hardens the recovery path and rebuilds the application shell.
Restore now resolves an interrupted transaction from the filesystem rather than
from the recorded status, so a force quit, a lost mount or a power cut during a
cleanup no longer strands files or leaves a session that cannot be restored.
The mandatory 30-day recovery window applies to every quarantine session
whatever the age of its projects, and no backup is selected in a folder holding
a project the reader could not classify. The main window moves to a sidebar
with the three workspaces, a light/dark switch and title bar accessories.

Version 0.10.0 reorganizes the native app into clear **Scan & Review**,
**Cleanup** and **Recovery** workspaces. It adds progressive scan options,
result-oriented English copy, a compact DAW format column, persistent window
sizing and vertically stacked cached project/media tables that remain usable on
laptop screens. The final user workflow exposes one complete **Scan Folder**
action; network-specific inventory remains an internal diagnostic capability,
not a product mode. Version 0.9.0 added an operator-controlled, atomic publication backend for
DAW-validated separated projects, with a hash receipt and recoverable
withdraw/restore transaction. It does not retire or modify the mother folder.
Version 0.8.1 added a filesystem-identity safety guard for macOS Unicode path
aliases so the CLEANED survivor can never be classified as an old project
artifact. Version 0.8.0 added shared-folder separation planning, hash-verified copy-only
staging and operator-confirmed Nuendo CONTROL/CLEANED batch quarantine with
cross-session rollback. These build on the fail-closed Archive Queue, paginated,
locally cached result view and structured phase/progress display. Live updates
are batched to keep scrolling responsive.

The v1 archive path now standardizes historical projects through Nuendo 15
before cleanup. A read-only Archive Queue groups every project that shares
media, records missing or ambiguous-reference blockers and tracks the required
normalization, Pool cleanup, self-contained archive and reopen-validation gates.
No queue item can authorize deletion merely because a file looks unreferenced.

The selected folder can be on a local disk or any mounted server volume.
Projects appear in the table as soon as they are found, and the macOS UI reports whether
each candidate project matches an application-validated exact Pool topology.
For a disposable controlled copy only, a double-confirmed pilot can back up and
rewrite those project references, move the matching media to recoverable
quarantine and restore both together. A selected shared quarantine location is
remembered on each Mac. Permanent deletion is available only for a fully
validated session after the recovery policy and explicit authentication pass.

Created by **Franck Reisner / Studio89** as a good-faith third-party utility for
people maintaining their own project archives.

> DAW Project Cleaner is not affiliated with, authorized by or endorsed by
> Steinberg. Cubase and Nuendo are trademarks of their respective owner.

## Why quarantine first?

A pool-side reference is useful evidence, but it is not universal permission to
delete a file. Projects can share media, older versions can serialize data
differently, and a project may still remember media that is not on its timeline.
The app therefore labels items as candidates while separately showing whether
the complete project topology is **Ready** or **Report only**. Controlled-copy
Apply requires two confirmations, revalidates the scan, backs up and rewrites
every affected project, stages and reparses the result, then performs atomic
same-filesystem media moves. Restore returns the exact original projects and
media if anything is unexpected.

## Features

- recursively discovers `.cpr` and `.npr` files;
- renders at most 200 project and 500 media rows per page;
- batches live table refreshes and throttles high-frequency progress updates;
- shows the active phase, current file and exact percentage throughout a scan;
- inventories Audio, Edits, Freeze, Mixdown/Exports and backup folder sizes;
- hard-locks every Apply path for incomplete reports;
- validates complete `RIFF/NUND` and `RIF2/NUND` container/chunk coverage;
- reads embedded Cubase/Nuendo writer and version information;
- distinguishes active-side and pool-side media evidence;
- matches media against a unique sibling `Audio` folder;
- protects files active in another discovered project;
- skips directory and file symlinks;
- supports configurable archive/export exclusions;
- reads legacy root-level `.bak` files and modern backup-folder projects;
- defaults to Archive Cleanup: classified backups are hashed, not parsed, do
  not protect media and are selected for recoverable quarantine;
- offers optional Working Project modes that keep all or the newest 10/5/3/1
  backups and protect their referenced media;
- never rewrites backup projects;
- shows discovery state followed by exact file count, percentage and current filename;
- records permission and parse errors without guessing;
- processes everything locally with no telemetry or network service;
- stores its JSON report in macOS Application Support, not in the archive.
- provides recoverable quarantine with project backups, state and audit log;
- exposes a double-confirmed, marker-gated exact-profile Apply pilot for disposable copies;
- validates a DAW-created CONTROL/CLEANED pair and exposes a double-confirmed,
  Restore-only normalized-project quarantine pilot;
- automatically rolls back both project and media changes after a pilot failure;
- remembers up to 12 shared quarantine locations per Mac;
- enforces same-filesystem quarantine moves without duplicate media;
- keeps a mandatory 30-day recovery window on every quarantine session,
  whatever the age of the projects it holds;
- allows permanent purge only after that window, macOS owner authentication
  and an exact typed confirmation;
- requires warning and typed confirmations before controlled-copy Apply.

## Quick start

1. Create a disposable local copy; never begin with the only server archive.
2. Open **DAW Project Cleaner.app**.
3. Choose a root folder broad enough to include projects that might share media.
4. Choose a shared quarantine folder on the same mounted server filesystem.
5. Click **Scan Folder**.
6. Review the backup policy decisions. Apply the backup policy separately if
   older backup files should move to quarantine, then run a fresh scan.
7. Select a project to review its media evidence.
8. After the complete scan, select individual Ready projects or use
   **Select All Ready**. Projects sharing candidate media are selected as one
   safety group.
9. Confirm that the chosen projects say **Ready**, then choose
   **Clean Selected Controlled Copies…**.
10. Accept the copy warning and type `CONTROLLED COPY APPLY`.
11. Open every affected project without resaving it, then Restore or keep the
    quarantine for its recovery period.

The report is saved under:

`~/Library/Application Support/DAW Project Cleaner/reports/latest-scan.json`

Quarantine sessions are stored under `sessions/` in the selected shared
quarantine folder. Each session retains verified project backups, state and an
audit log. Quarantine does not reclaim filesystem space while media remains in
the session.

## Controlled-copy rewrite pilot

The macOS UI creates the exact disposable-copy marker only after two explicit
confirmations. The backend refuses unsupported application-validated
topologies, partial Pool/media mappings, stale scans, links, changed files and
cross-project active use. A matching application version alone is never enough.

The pilot stages and validates rewritten projects, verifies project backups,
atomically replaces projects, then moves matching media into the same-filesystem
session. `restore` returns media first and then restores the original project
bytes. Purge revalidates the rewritten project, backup and every quarantined
media digest before any permanent deletion.

## Supported read profiles

The reader validation corpus includes real projects from Cubase 5 through Cubase 12 and
Nuendo 11 through Nuendo 15. Both 32-bit `RIFF/NUND` and 64-bit `RIF2/NUND`
containers are recognized. Filename extension alone is never trusted as a
format or product identifier.

See [Supported formats](docs/SUPPORTED_FORMATS.md) for details and limitations.

## Build from source

Requirements:

- Apple Silicon Mac running macOS 11 or later;
- Xcode Command Line Tools;
- Python 3.9 or later;
- PyInstaller.

```bash
python3 -m pip install pyinstaller
./scripts/build_macos_app.sh
```

The script creates `dist/DAW Project Cleaner.app`, compiles an arm64 AppKit UI,
bundles the Python scanner and applies an ad-hoc local signature. Public release
distribution should use an Apple Developer ID and notarization.

## Tests

```bash
python3 -m unittest discover -v
swiftc -typecheck native/App.swift
```

Tests use generated temporary files only. No Steinberg software, code, samples
or user projects are included in this repository.

## Controlled archive audit

The CLI includes a read-only topology audit for shared parent folders and media
outside the conventional Audio directory:

```bash
python3 -m daw_project_cleaner.cli archive-audit /path/to/archive \
  --report /local/private/report.json --workers 2
```

It inventories Audio, Edits, Freeze/Freezes and other supported media locations,
protects all matches for ambiguous basenames, and emits a copy-only separation
plan. It never authorizes cleanup or project rewriting.

Create a read-only Nuendo 15 normalization queue from a complete audit:

```bash
python3 -m daw_project_cleaner.cli archive-plan /local/private/audit.json \
  --report /local/private/archive-queue.json --target "Nuendo 15"
```

See [Archive Queue](docs/ARCHIVE_QUEUE.md) for its dependency-family and final
validation rules.

## Documentation

- [Project report](PROJECT_REPORT.md)
- [User guide](docs/USER_GUIDE.md)
- [Safety model](docs/SAFETY_MODEL.md)
- [Supported formats](docs/SUPPORTED_FORMATS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Privacy](docs/PRIVACY.md)
- [Legal and ethical scope](docs/LEGAL_AND_ETHICS.md)
- [Build and release](docs/BUILD_AND_RELEASE.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## Support development

If this utility saves you time, voluntary support is welcome:

<https://buymeacoffee.com/franckreisner>

![Buy Me a Coffee QR code](assets/support-qr.png)

Support is voluntary and does not purchase a warranty, endorsement or priority
support commitment.

## License

DAW Project Cleaner's original source code is available under the [MIT License](LICENSE).
Third-party names and trademarks remain the property of their owners; see [NOTICE](NOTICE.md).
