# Verified publication pilot

Version 0.9.0 can publish DAW-validated separated projects as one complete,
self-contained server container. This remains an operator-controlled pilot and
is not yet exposed as a general one-click archive action in the macOS UI.

## Safety contract

- Every input must be a final-gate CONTROL/CLEANED validation report.
- Pool-only media and superseded project artifacts must already be in
  recoverable quarantine.
- The CLEANED project hash and active reference set are revalidated.
- Every active media reference must resolve to exactly one regular non-link
  file inside that project's controlled copy.
- The destination must not already exist and must not be inside a source root.
- All output is copied into a hidden same-parent staging directory.
- Source and copied SHA-256 hashes must match before publication.
- A receipt is included in the container.
- The complete container becomes visible with one same-filesystem rename.
- Sources and the legacy mother folder are never moved, modified or deleted.
- Mother/master retirement remains a separate blocked decision.

## Recovery

`withdraw-publication` rechecks the entire receipt before atomically moving the
published container into a same-filesystem quarantine session. If any published
file changed, withdrawal fails closed. `restore-publication` refuses an occupied
destination and restores the exact container by atomic rename.

Permanent deletion is not part of publication. A published batch and its
legacy mother folder may coexist until the user has completed the required DAW
checks and every blocked sibling/master question is resolved.

## Case A evidence

Between 2026-08-13 and 2026-08-15, seventeen independently normalized Case A
child projects were published in three atomic batches as 1,973 receipt-pinned
files / 13,470,786,020 bytes. Independent full rereads of the server containers
matched 820/820, 992/992 and 161/161 SHA-256 values. Representative projects
from the first two batches opened and played directly from the server in
Nuendo 14 without missing-media prompts. The third batch's new external-media
case was opened after physical quarantine on its controlled local copy before
publication.

All 20 project files in the legacy mother folder retained their pre-publication
hashes after every batch. Two child projects remain blocked because their exact
active MP3 files have not been found. No similarly named WAV may be substituted.
The unsupported master remains protected and the legacy mother folder has not
been retired.
