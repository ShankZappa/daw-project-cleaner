# Safety model

## Public release invariant

The app scans without modification by default. Cleanup is a separate,
explicit controlled-copy workflow: revalidate, back up affected projects,
rewrite only application-validated exact Pool topologies, quarantine matching
audio, test in the DAW, then restore both layers. The UI and CLI pilot are
restricted to roots explicitly marked as disposable copies. Permanent purge
remains disabled.

## Fail-closed checks

- complete container length must match the file size;
- every top-level chunk must fit and cover the complete container;
- exactly one main arrangement root/archive must be present;
- exactly one supported project-pool boundary must be present;
- malformed string fields are ignored rather than guessed;
- a unique, real sibling Audio folder is required for size mapping;
- duplicate media basenames are ambiguous;
- project and media symlinks are skipped;
- unreadable projects and filesystem errors are visible;
- active use in any discovered project clears the candidate flag;
- conflicting classifications clear the candidate flag;
- files merely absent from one project never become candidates.

## Trust boundary

Project files are untrusted binary input. The parser uses bounded reads and
validates declared lengths before extracting supported metadata. It does not
load plugins, execute project content or start Cubase/Nuendo.

The scan report is written to the current user's Application Support directory
using a temporary file followed by an atomic replacement. Cleanup sessions are
created only below `.daw-project-cleaner-quarantine` in the selected root.
The ordinary quarantine path requires high parser confidence. Only the
disposable-copy pilot may accept a report-only reader profile, and then the
project must still pass a registered exact writer, staged reparse, full
Pool/media mapping and all transaction checks.

## Candidate semantics

Candidate means “worth reviewing”, not universal proof. Quarantine therefore
requires two confirmations and validates every project digest, pool-side
occurrence, media path, size, file type, symlink chain and cross-project guard.

Moves use same-filesystem atomic replacement. Every session contains verified
project backups, durable state and an append-only audit log. Restore refuses
collisions or a project changed after Apply. The controlled-copy pilot requires
every pool-only reference in an affected project to map to a quarantined file;
it stages and reparses the rewritten project before any original is replaced.
Any caught failure restores moved media and exact original project backups.
Permanent deletion is hard-disabled while this remains a pilot. Development
transaction tests use temporary generated files and a disposable real-format
copy; no server archive is modified.

## Nuendo-normalized disposable copies

The CONTROL/CLEANED path delegates project serialization to Nuendo and does not
modify binary project data. Read-only validation requires the CLEANED survivor
to retain all mapped active media, contain no Pool-only references and pass the
supported structure gate. Apply then verifies the disposable-copy marker,
report and current file hashes before any move.

Unused media and superseded project/backup artifacts move atomically into the
same session, with durable state and audit records. CLEANED remains untouched.
A caught interruption rolls back completed moves; Restore checks hashes and
occupied paths before returning everything. Normalized sessions cannot enter
the permanent-purge UI in this validation release.
