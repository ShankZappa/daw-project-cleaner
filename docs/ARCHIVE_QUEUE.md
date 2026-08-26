# Archive Queue and Nuendo 15 normalization

## v1 objective

The primary v1 workflow is bulk archive reduction without missing-media prompts
in surviving projects. Historical CPR/NPR files do not need a universal custom
writer. They are normalized by Nuendo 15 before any source media becomes
eligible for cleanup.

## Non-negotiable invariant

A media file is not deletable until every surviving project in its dependency
family has been normalized, its unused Pool entry has been removed by the DAW,
all remaining references resolve to existing files, and the normalized project
has reopened successfully in Nuendo 15.

Projects sharing even one uniquely resolved media path belong to the same
dependency family. The complete family advances through the queue together.
This prevents an older version or alternate mix from losing media selected by a
different project.

Projects stored directly beside one another in the same legacy parent folder
also remain one family, even if their currently resolved media sets do not
overlap. Possible matches from ambiguous references connect families but remain
blockers; they are never treated as proof that cleanup is safe.

## Queue stages

1. **Normalize in Nuendo 15** — open every family member and save a new-format
   copy; preserve the original for rollback.
2. **Remove unused media from Pool** — use the DAW's supported Pool operation,
   not a heuristic binary patch.
3. **Create self-contained archive** — gather only media required by the
   surviving normalized project set.
4. **Validate references** — build a manifest and require every referenced path
   to exist, be unambiguous and match its recorded size/hash.
5. **Validate DAW open** — reopen in Nuendo 15 and explicitly record that no
   missing-media dialog appeared.
6. **Quarantine original** — atomically move the old tree on the same filesystem
   and retain the complete rollback manifest.

No queue stage directly authorizes permanent deletion. Purge remains a separate
authenticated action after the applicable recovery period.

When a DAW-cleaned project replaces an older project, every older CPR/NPR and
backup that still remembers the removed media belongs in the same recoverable
transaction as that media. Leaving the old project beside the cleaned survivor
would reintroduce a missing-media prompt after quarantine. The normalization
validator therefore hashes and lists non-surviving project artifacts explicitly;
it never treats the cleaned file alone as permission to delete audio.

## Current implementation boundary

`archive-plan` creates a read-only planning report from a complete
`archive-audit` report. It computes shared-media dependency families, identifies
missing/ambiguous reference blockers and creates the six pending workflow
stages. The command never launches Nuendo, writes to an archive, moves media or
marks cleanup as authorized.

The next implementation gate is a controlled operator-assisted normalization
session on generated/disposable fixtures. Fully unattended macOS Accessibility
automation is not a safety dependency and will not be enabled until it proves
reliable across cancellation, dialogs and Nuendo updates.

## Controlled DAW-normalized transaction

After the operator-confirmed DAW reopen gate, `apply-normalized-pilot` can be
used only on a directory carrying the explicit disposable-copy marker. It
reparses and hashes the cleaned survivor, revalidates every candidate and old
project artifact, then moves those files into a same-root session using atomic
same-filesystem renames. State and audit data are persisted around every move.
Any caught interruption rolls completed moves back; Restore independently
revalidates every quarantine hash and returns moves in reverse order. The pilot
never permanently deletes files and remains separate from production Apply.

The first real Nuendo 15.0.20 disposable project completed this full sequence,
including a DAW reopen after physical media quarantine, exact 15-file Restore
and a second successful Apply. This validates the transaction mechanics and the
no-missing-media outcome for that project family; it does not yet authorize
unattended server-wide cleanup.
