# DAW Project Cleaner — development report

## Executive summary

DAW Project Cleaner was created to help Studio89 and other audio professionals
understand oversized Cubase/Nuendo archives before carrying out cleanup. The
software recursively inventories projects and their media evidence. Scanning is
non-modifying; optional cleanup uses a recoverable quarantine before deletion.

The public release separates validated reading and guarded filesystem actions
from experimental binary project-writing work. It contains no user projects,
proprietary application files, licensed samples, application code, activation
logic or binary project-modifying features.

## Problem statement

Long-lived DAW archives often contain many takes and pool entries that no longer
appear on the arrangement. Manual inspection is slow across a server containing
hundreds or thousands of projects. Automatic deletion, however, can break
projects when media is shared, references are ambiguous or project formats vary.

The default remains a reliable inventory and evidence report. Optional cleanup
is deliberately staged: quarantine, DAW testing and restore. Purge is disabled.

## Implemented scope

The application:

- walks a user-selected root recursively;
- honors common backup/export exclusions;
- does not follow symlink directories or media links;
- reads `.cpr` and `.npr` outer structure with strict boundary checks;
- records the embedded product, version and serialization fingerprint;
- finds the main arrangement and project pool;
- extracts supported audio names from structured fields;
- labels active-side, pool-side-only and unreferenced-on-disk media;
- maps unique basenames to a sibling `Audio` folder;
- detects cross-project active use inside the selected root;
- calculates potential review space;
- emits a local JSON report and shows it in a native macOS interface.
- revalidates candidates and project digests before any move;
- backs up affected project files and quarantines media atomically;
- restores sessions and refuses permanent purge while project rewriting is unavailable.

## Validation summary

Read-only analysis was exercised against 20 user-owned archive examples spanning
Cubase 5–12 and Nuendo 11–15. All examples passed complete outer-container and
chunk validation and exposed a readable project pool. The corpus included both
32-bit and 64-bit container families and several internal class generations.

Two small, independently created test projects were also used during private
development to compare application-generated pool cleanup behavior. Generated
copies opened and resaved in their matching applications. Those write experiments
are intentionally **not** part of this public repository or release.

Public automated tests use generated synthetic fixtures only.

## Important findings

- `.cpr` and `.npr` extensions are not reliable product/version identifiers.
- Cubase and Nuendo share a long-lived project-pool model.
- The container family and internal class fingerprint must be checked together.
- Media appearing only on the pool side is a review candidate, not proof that
  deletion is safe.
- Scanning a broad root is important because separate projects can share media.
- One unreadable project can invalidate a global cleanup assumption.

## Safety decisions

Version 0.5 writes nothing during Scan. A separate double-confirmed UI pilot is
available only on a disposable controlled copy when every candidate project
matches an application-validated exact topology. It creates a hidden same-root
session, verified project backups, durable state and an audit log, stages and
reparses rewritten projects, then atomically moves matching media. Restore
returns exact original project and media bytes. Permanent deletion remains
disabled.

The app fails closed on malformed containers, ambiguous media matches,
unsupported layouts, permissions errors and symlinks. Files absent from one
project are not treated as disposable.

## Privacy and security

All processing occurs locally. There is no analytics SDK, account system,
upload, cloud API, update service or network request in the scanner. The only
network action is an explicit user click on the voluntary support button, which
opens a browser URL.

Project paths and filenames can be sensitive. Reports remain local and should be
reviewed before sharing in an issue.

## Public-release legal hygiene

The repository contains only independently written source code and generated
tests. It excludes all user project corpora, application binaries, proprietary
samples, exact private test data and experimental write tooling.

The project purpose is interoperability with project files belonging to the
user. It does not inspect or modify Steinberg application binaries, bypass
license management, circumvent access controls or imitate the applications.

This is a technical publishing review, not legal advice. Maintainers should
obtain qualified counsel before materially expanding the scope or distributing
automatic project-writing functionality.

## Release status

Version 0.5 provides broad read-only inventory plus an opt-in, recoverable
project-consistent controlled-copy pilot for a small exact-profile registry. It
does not provide unrestricted server cleanup or permanent purge.

## Roadmap gates

Any future automatic action should require all of the following:

1. a documented, exact format fingerprint;
2. multiple controlled projects with varied pool shapes;
3. application open, playback and resave validation;
4. project backup, atomic write and recovery tests;
5. cross-project shared-media protection;
6. an explicit preview and user confirmation;
7. an updated legal/security review;
8. no circumvention or application-binary modification.

Projects outside the application-validated exact topology registry remain
report-only.
