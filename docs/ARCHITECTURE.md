# Architecture

## Components

```text
Native macOS AppKit UI
        │ launches bundled local process
        ▼
Python CLI backend
        │
        ├── recursive project discovery
        ├── internal diagnostic metadata inventory
        ├── strict container/project reader
        ├── Audio-folder mapper
        ├── cross-project candidate guards
        ├── shared-media Archive Queue planner
        ├── Nuendo CONTROL/CLEANED validator
        ├── shared-folder separation planner and copy rehearsal
        ├── atomic JSON report writer
        ├── quarantine / restore
        └── UI-exposed controlled-copy rewrite/restore pilot (permanent purge gated off)
```

The UI never parses project data directly. The backend accepts a root and report
destination, emits one JSON event as each project finishes, prints progress and
exits nonzero on fatal errors. Streamed rows are preview-only; the final report
replaces them after global guards complete.

## Modules

- `format.py`: bounded RIFF/RIF2 and supported project metadata reader;
- `scanner.py`: discovery, exclusions, media matching and global guards;
- `remote_scan.py`: internal diagnostic metadata inventory with bounded
  project-header identification, atomic checkpoints and resume state; it is
  not exposed as a separate final-product scan mode;
- `model.py`: stable JSON-compatible result model;
- `archive_queue.py`: fail-closed shared-media family and Nuendo 15 workflow planner;
- `normalization_validation.py`: read-only CONTROL/CLEANED comparison, active
  survivor mapping, candidate hashing and final validation gate;
- `separation_plan.py`: per-project self-contained manifests, dependency cost,
  blocker reporting and independent master-retirement gate;
- `separation_stage.py`: non-destructive hash-verified staging copies with
  atomic publication and interruption cleanup;
- `cli.py`: scan, archive-audit, quarantine, controlled-copy pilot and restore entry point;
- `transaction.py`: fail-closed session validation and filesystem transactions;
- `native/App.swift`: AppKit interface and support/about presentation.

## Concurrency

Project inspection uses a bounded thread pool. The default is four workers and
the backend caps the value at eight to avoid saturating mounted storage.

The AppKit tables are paginated (200 project rows and 500 media rows) and remain
virtualized. Streamed project events are deduplicated by a path set, then
coalesced into a maximum of two table refreshes per second. Progress updates are
also throttled independently. This prevents fast local scans from flooding the
main run loop and keeps page navigation responsive while scanning continues.

## Filesystem policy

Directory traversal does not follow symlinks. Scanning opens project/media files
for reading only. Cleanup uses a same-root hidden quarantine so moves remain
atomic. The pilot stages and reparses rewritten projects, backs up originals,
atomically replaces projects and only then moves media. Restore reverses both
layers. Selective Apply accepts explicit report-pinned project paths and refuses
an incomplete set when candidate media is referenced by an unselected project.
Permanent unlink is disabled.

Every transaction entry point requires the backend's complete validation report.
Interrupted or diagnostic inventory JSON cannot authorize a move, rewrite or
deletion even when invoked outside the GUI.

## Packaging

PyInstaller creates a self-contained arm64 backend. Swift compiles the AppKit
frontend. Both are placed in a normal `.app` bundle with the support QR resource
and an ad-hoc local signature.

## Exact-profile writer boundary

Experimental writers dispatch on the complete product/version/container/class
fingerprint and refuse unregistered Pool shapes. UI readiness additionally
matches an application-validated topology signature and complete media mapping.
The transaction repeats that topology gate and requires an exact
disposable-copy marker. All changes have verified backups, durable state and
audit records.

The separate Nuendo-normalized path never patches project bytes. It accepts a
DAW-resaved CLEANED survivor only after the user confirms an open/play test,
then revalidates report-pinned hashes and moves unused media plus superseded
project artifacts into one recoverable same-root session. The native UI shows
exact per-file transaction progress. Normalized sessions are restore-only and
excluded from permanent purge.
