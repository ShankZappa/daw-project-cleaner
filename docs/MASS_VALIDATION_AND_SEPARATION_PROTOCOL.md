# Mass validation and project separation protocol

The application must not perform mass cleanup while project-file rewriting is
disabled. A cleanup that removes media but leaves CPR/NPR pool records is not a
project-consistent cleanup.

## Validation ladder

1. **Read-only inventory** — discover every project and relevant media location,
   including Audio, Edits and Freeze/Freezes.
2. **Reference graph** — protect ambiguous basenames, missing media, shared paths,
   symlinks and any project affected by parse errors.
3. **Copy-only separation rehearsal** — build a staging tree from generated or
   disposable copies; preserve active and pool-only references.
4. **Profile-specific rewrite test** — write a new project copy only for an exact
   format fingerprint with controlled before/after evidence.
5. **DAW validation** — open, play, inspect the Pool, save and reopen in the
   matching application generation.
6. **Transactional pilot** — one disposable real-world copy, with project and
   media restored together on any failure.
7. **Limited batch** — a small homogeneous version/profile cohort.
8. **Mass rollout** — only profiles that have passed every earlier gate.

As of 2026-08-08, step 6 has passed for both a disposable Nuendo 15.0.30
interleaved-pool copy and a real-world Nuendo 14.0.41 Case B copy. In the N14
test, Apply retained 12 active references, removed six Pool-only records,
quarantined the matching six media files (105,996,084 bytes), and Restore
reproduced the original project plus every media SHA-256 hash. The transaction
also proved that application-validated older profiles may remain report-only in
the general reader while the marker-gated pilot relies on the stricter exact
writer gate. Normal quarantine still requires high reader confidence.

Step 7 subsequently passed for a two-project Nuendo 14.0.41 batch containing
the native two-unused shape and the real Case B six-unused shape. Apply retained
13 active names, removed eight Pool-only records and quarantined 220,416,532
bytes. Both projects opened and played correctly in Nuendo 14 and showed the
intended Pool state. Restore reproduced both original project hashes and all
eight media hashes, leaving no media in quarantine. Step 8 remains disabled;
the result applies only to the two registered exact Pool shapes.

## Transaction bundle

Each session must contain the scan report, input hashes, exact project backups,
media hashes, planned and completed operations, rewritten-project output hashes,
DAW validation state and an append-only audit log. Restore must atomically put
back both the original projects and all quarantined media. Permanent deletion is
a separate, delayed and double-confirmed operation.

## Separation commit

New per-project folders are first created below a hidden same-filesystem staging
session. Shared media is copied into every project that needs it. Missing or
ambiguous references block that project. The original mother folder is never
deleted during commit; it is renamed into quarantine after all new projects have
passed hash and DAW validation. Purge is allowed only after the chosen retention
period.

## Implemented read-only plan and copy rehearsal

`separation-plan` now converts a complete archive audit into one explicit
manifest per project. It preserves the source media role (`Audio`, `Edits`,
`Freeze`, images and other supported locations), detects destination filename
collisions, reports the cost of duplicating shared media and blocks every
missing, ambiguous or unsupported project.

Master retirement is evaluated independently. Reference coverage by child
projects is necessary but never sufficient: all children must also be
normalized, opened/played/resaved, published and retained through a reversible
mother-folder quarantine. A master with no supported media records remains
unverifiable and cannot be retired automatically.

`stage-separation-copy` is a controlled copy-only rehearsal for ready manifests.
It checks free space, revalidates the audited project hash, rejects symlinks,
hashes every source and copied file, publishes the completed tree atomically and
removes only its own hidden staging tree after a caught interruption. It never
changes the mother folder and does not authorize cleanup.

Normalized batches preflight every CONTROL/CLEANED report before the first
move, reject duplicate roots and shared planned sources, then apply one durable
session per project. If a later project fails, every earlier completed session
is restored in reverse order. The operator still reopens every CLEANED survivor
in the matching DAW after physical quarantine; batch completion alone is not a
DAW-validation claim.
