# Support

DAW Project Cleaner is an independent good-faith project by
Franck Reisner / Studio89.

## Reporting a problem

**There is no public issue tracker yet.** Until one exists, reports go to the
author directly. Please do not wait for a channel to open if you have lost data
or the tool refused something it should have accepted — those are the reports
worth having.

Include:

1. **The version.** `daw-project-cleaner --version`. Every scan report and
   quarantine session also records it as `tool_version`, so if you still have
   the report, the version is in it.
2. **What you ran** — the exact command, or which button in the application.
3. **What it said.** A refusal prints one line beginning `Refused:` and exits
   with status 3; a storage failure prints `Storage error:` and exits 4. Copy
   the line. If you got a Python traceback instead, that is itself a defect —
   send the whole thing.
4. **The session `audit.jsonl`**, if a cleanup was involved. It records every
   move with its digest and is the single most useful artifact.

Do not attach client projects, licensed audio, full scan reports or server
paths. A scan report lists every media filename in the archive. If a
reproducer is needed, build one with generated fixtures — `tests/helpers.py`
shows how to create a project file with known contents.

## What to expect

This is one person's tool, published because it may help other people with the
same problem. There is no service level, no guaranteed response time and no
warranty. Voluntary support at <https://buymeacoffee.com/franckreisner> does
not change any of that.

![Buy Me a Coffee QR code](../assets/support-qr.png)

## Recovering before reporting

If a cleanup went wrong, recovery comes first:

- Every cleanup moves files to a recoverable quarantine session; nothing is
  deleted until a session has passed a 30-day window, owner authentication and
  a typed confirmation.
- `daw-project-cleaner restore <session>` returns every file to its exact
  original path and verifies each digest.
- Restore is resumable. If it was interrupted, run it again.
- If it refuses, read the `Refused:` line before doing anything else — it names
  the file it could not resolve. Do not move files by hand first; that removes
  the evidence Restore uses.
