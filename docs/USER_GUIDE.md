# User guide

## Before scanning

Scanning is read-only. Apply can rewrite copied projects and move audio, so use
a disposable copy and keep a healthy independent backup. Choose a root that
includes every project likely to share an Audio folder. Close or pause server
migration tools if paths are changing rapidly.

The app has three workspaces:

- **Scan & Review** chooses the root, runs a read-only scan and displays
  locally cached project and media pages;
- **Cleanup** contains only actions backed by a completed validation;
- **Recovery** remembers quarantine locations and provides Restore or eligible
  authenticated permanent deletion.

Backup policy and excluded folder names are available under **Show advanced
scan options**. They stay out of the main path but retain their last settings.

## Why the scan must finish

The app exposes one scan. It first discovers the complete project and backup
set, then reads each file while showing an exact `read / total` percentage.
Finishing the complete folder is necessary because an audio file that looks
unused in one project may still be active in another project or retained
backup. These checks are automatic; the user does not need to choose a
technical scan mode.

Project results are shown 200 at a time and media results 500 at a time. Use
the Previous/Next controls instead of placing every archive row into one large
scrolling table. Live rows are refreshed in batches, so navigating existing
pages remains responsive during a scan.

## Running a scan

1. Open DAW Project Cleaner.
2. Click **Choose Folder…** and select the archive root.
3. If needed, open **Show advanced scan options** and review the exclusion list.
   Defaults omit backups, edits, exports, bounces and
   freeze folders to reduce duplicate/noise-heavy results.
4. Click **Scan Folder**.
5. Wait for every discovered project to be processed.

Projects now appear in the table incrementally as they are read. The summary
shows scanned projects, candidates found so far, Ready projects and errors.
These rows are preliminary until the complete scan has applied cross-project
shared-media guards. Apply and selection remain disabled while scanning.

While scanning, the same button changes to **Stop Scanning**. Stopping ends the
backend process without producing or applying a partial scan report. Choose a
new folder and scan again. Already streamed rows remain visible as a read-only
partial inventory, but cannot authorize Apply. The app also refuses to scan
when the folder field is empty, preventing an accidental scan of its process
working directory.

The project list shows the embedded writer compactly as, for example,
**Nuendo 15** or **Cubase 12**; hover for the full version. Its **Cleanup** state
is **Ready** when the exact version and Pool topology passed
controlled application validation and all Pool-only media map safely in this
scan. **Report only** means Apply is blocked. A
`.cpr` extension can still identify a project written by Nuendo, so the embedded
information is more important than the filename.

## Understanding media classifications

- **active**: the supported media name has evidence on the arrangement side of
  the project pool boundary;
- **pool_only**: the supported name was found only on the pool side;
- **unreferenced_on_disk**: a file exists in the Audio folder but its basename
  was not found in that project.

Only a uniquely matched pool-only file can become a **Review** candidate.
Unreferenced-on-disk files are never candidates because absence from one project
is not sufficient evidence.

## What “Potential” means

Potential space is the sum of review-candidate file sizes. It is an estimate,
not a promise that the files can be deleted. Verify candidates in the matching
DAW and consider shared/archived project versions before manual cleanup.

## Project backup policy

The scanner reads `.bak` files regardless of location and treats `.cpr`/`.npr`
files inside `Backup`, `Backups`, `Auto Saves` and `Autosaves` folders as
project backups. The default **Archive Cleanup** policy hashes each
unambiguously matched backup but does not parse its contents or use it to
protect media. Every classified backup is selected for recoverable quarantine.

Optional **Working Project** policies keep all or the newest 10, 5, 3 or 1
backups. In these modes retained backups are parsed and protect every mapped
media reference. The selected policy is remembered on each Mac.

Backups are never rewritten. Safely classified backups can be reviewed and
moved intact with **Apply Backup Policy…**. Ambiguous, unreadable or unmatched
backups are always kept. After applying a backup policy, run a fresh scan before
project cleanup. Restore returns quarantined backups to their exact original
paths.

## Controlled-copy Apply and restore

After a complete scan, use each project's checkbox, **Select All Ready** or
**Clear Selection**. Selecting a project automatically includes every Ready project
sharing the same candidate media; deselecting removes that dependency group.
The backend repeats this closure check and refuses any incomplete selection.

Open **Cleanup** and use **Clean Selected Controlled Copies…**. It is enabled
only when every project with candidates
in the selected dependency groups is Ready and the scan has no parse errors. It
must never be used on the only copy of an archive. The first prompt confirms the
selected root is disposable; the second requires `CONTROLLED COPY APPLY`.

The backend then revalidates all scanned project hashes and each candidate's
Pool-side evidence, size, path and symlink status. It creates verified project
backups, stages and reparses every exact rewrite, atomically replaces projects
and moves matching media into the selected shared same-filesystem quarantine.
The chosen location is remembered on that Mac, and additional locations remain
available in the selector. Any caught failure
rolls back both layers.

Open and test affected projects without resaving them. **Restore Last Cleanup…**
returns verified media and exact original project bytes. It refuses changed
projects, occupied original paths or hash mismatches.

The resulting session stores original projects, rewritten hashes, media hashes,
operation state and an audit log. The normal `restore` command restores both
the audio and the original project files.

## Nuendo-validated CONTROL/CLEANED workflow

This workflow is for a disposable project copy that has already been cleaned
and resaved in Nuendo. Keep the original project as **CONTROL** and name the
Nuendo-resaved survivor **CLEANED**. Confirm in Nuendo that CLEANED opens,
plays and produces no missing-media prompt before continuing.

1. Click **Validate Nuendo Cleanup…** and choose CONTROL, then CLEANED.
2. Confirm the Nuendo reopen/play check. Validation is read-only: it compares
   both projects, maps retained active references and hashes every proposed
   quarantine file.
3. Review the exact media count, reclaimable size, old project files and
   backups. Nothing has moved yet.
4. Click **Quarantine Validated Copy…**, confirm this is a disposable copy and
   type `QUARANTINE NORMALIZED COPY`.
5. Follow the exact progress percentage and current filename. CLEANED and all
   of its active media stay in place; unused media plus CONTROL/old backup
   artifacts move atomically into a recoverable same-root session.
6. Reopen CLEANED in Nuendo without resaving and verify playback again.

To prepare a limited batch, repeat **Validate Nuendo Cleanup…** for each
CONTROL/CLEANED pair. Each successful pair is added to the validated queue; a
new validation for the same project folder replaces its earlier report. The
button changes to **Quarantine Validated Batch (N)…**, and **Clear Validated
Batch** removes the queue without changing files.

Batch Apply preflights every report and hash before its first move. It shows one
combined exact file count and percentage. Each project receives its own durable
Restore session. If a later project fails, earlier completed sessions are
restored automatically in reverse order. Reopen and test every CLEANED project
after the batch without resaving it.

**Restore Last Cleanup…** returns every moved media and project artifact to its
original path after hash and collision checks. These normalization sessions are
restore-only in this validation build and cannot be permanently purged from the
app.

Every quarantine session keeps a mandatory 30-day recovery window. The age of
the projects makes no difference: an archive consists mostly of old projects,
and those are the ones whose owner is least likely to open them, least likely
to notice damage and least able to reconstruct them. After the window, purge
still requires macOS owner authentication and typing
`DELETE QUARANTINE PERMANENTLY`. Purge keeps the project backup and audit log.

## Reports

The latest JSON report is stored at:

`~/Library/Application Support/DAW Project Cleaner/reports/latest-scan.json`

Reports can contain project paths and filenames. Treat them as potentially
sensitive and redact them before sharing.

Quick UI snapshots are stored as `latest-quick-scan.json`, with resume state in
`latest-quick-scan-state.json`; detailed safety scans remain `latest-scan.json`.
Quick and incomplete reports are rejected by
the backend even if passed to an Apply command manually.

## If a project cannot be read

The app reports an error and disables candidates globally when unreadable
projects could invalidate shared-media assumptions. Do not work around this by
removing the error from the JSON report. Instead, narrow down the format using a
generated or properly authorized sample and add a tested reader profile.

## Gatekeeper

The supplied local build is ad-hoc signed, not Apple-notarized. macOS may require
Control-click → Open the first time. A public downloadable release should be
signed with a Developer ID and notarized.
