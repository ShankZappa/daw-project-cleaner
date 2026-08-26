# Space-efficient migration, quarantine and recovery

## Target DAW

The studio production target is Nuendo 15; Cubase 12 is also installed. Old projects are
kept unchanged in the rollback bundle while the normalized working copy is
resaved in Nuendo 15 for NPR projects and Cubase 12 for CPR projects unless a
future migration policy explicitly standardizes CPR projects through Nuendo.

## One quarantine per volume

A same-filesystem move is atomic and consumes no second copy of the media.
Because `/Volumes/ServerOne` and `/Volumes/ServerTwo` may be different
filesystems, each volume needs one configurable central folder, for example:

`<volume>/DAW Project Cleaner Karantiin/<session-id>/`

A quarantine on another volume would require copying and temporarily double the
storage. The application must compare mount identity before planning a move and
fail closed when an operation would cross volumes.

## No-full-duplicate migration

1. Lock the source manifest with project and media hashes.
2. Back up the small original CPR/NPR files and transaction metadata centrally.
3. Create empty normalized project folders in a staging namespace.
4. Move uniquely owned media into those folders on the same filesystem.
5. Duplicate only media genuinely required by more than one self-contained
   project. Report the exact extra bytes before starting.
6. Keep ambiguous, missing, unused and unassigned media in central quarantine.
7. Write/resave the new latest-version project copy and validate it.
8. Commit by atomically renaming staging folders into their final names.

Before creating folders, group project-file versions into project families.
Projects with near-complete media-set containment (for example `FOOL.npr` and
`FOOL ATMOS.npr`) are proposed as one folder with multiple project files. The
proposal is shown for confirmation and avoids duplicating the same Audio set.

The rollback manifest records every old and new path. Restore moves media back,
restores every original project file and removes only empty staging directories.
During the 30-day validation period the migrated projects should not receive new
recordings or edits unless the transaction system also journals those changes.

## Default normalized project structure

```text
Project Name/
├── Project Name.cpr or Project Name.npr
├── Audio/
├── Edits/
├── Freeze/
├── Images/
├── Track Pictures/
├── Mixdown/
└── Auto Saves/
```

`Mixdown` contains user deliverables and is preserved even when the project has
no media reference to an export. `Images/*.peak` are rebuildable cache files but
are inventoried. Auto Saves are preservation data, not cleanup candidates.

## Found matches / Errors

The application will maintain a media index across user-selected search roots.
For a missing project reference it reports:

- **Exact** — verified embedded path/identity or previously recorded full hash;
- **Strong candidate** — unique basename plus compatible byte size, duration,
  channels, sample rate and BWF metadata;
- **Multiple candidates** — every possible path is protected and shown for
  manual selection;
- **Not found** — the project is blocked from migration or cleanup;
- **Cross-volume** — found, but would require a copy and explicit free-space
  approval;
- **Shared** — the file is referenced by more than one discovered project.

Basename alone can produce a review suggestion but never an automatic move.
After a user resolves a match, the selected file hash and decision are persisted
in the session manifest so the choice is reproducible and restorable.

## 30-day retention

The central session remains for 30 days after successful DAW validation. It
contains original project files, unresolved/unassigned media and the complete
rollback manifest, not a second copy of every migrated audio file. Purge remains
disabled until all projects in the session have a successful open, playback,
pool inspection, resave and reopen result.
