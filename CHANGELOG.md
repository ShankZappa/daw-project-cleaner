# Changelog

## Unreleased — archive-scale proportionality and scan progress

Found by running a full scan of the studio server from the Mac mini. Cleanup
could not be started at all, and the same sentence was attached to thousands of
files.

- **One unreadable project no longer disables cleanup for a whole archive.**
  `_apply_global_guards` was a single boolean over the entire scan: any
  unreadable project cleared every candidate everywhere. On the server one
  0-byte file among 1,725 projects disabled **81,216 candidates**, of which
  only **12** were actually in an affected folder. The guard is now bounded to
  the folder the doubt belongs to, using the same rule as
  `find_backup_audio_dir`. Measured against the real report: 81,204 candidates
  and 506.9 GiB return for review.
- **The interface no longer locks Apply because of an unreadable project
  elsewhere.** The selection already has to be a subset of Ready, which the
  backend validates per project, so the global error term only blocked work.
  The count is now reported beside the selection instead of replacing it.
- **`archive_queue` used its own narrower definition of a resolved
  reference.** The audit and the separation planner share
  `RESOLVED_REFERENCE_STATES = {"unique", "path_evidenced"}`; the queue tested
  against `{None, "unique"}` and reported every path-evidenced reference as
  blocking — **179,404 of 191,413 blockers, 93.7%**. Blocked families drop from
  98 to 41. The definition is now imported, not duplicated.
- **An empty project file is described accurately.** Cubase and Nuendo reserve
  a filename before writing its contents, so a 0-byte project is a reserved
  name, an interrupted save or a save still in progress — not a damaged
  project, and a live archive can be scanned while one is being written.
- **A recorded path resolves across Unicode normalisation.** A report written
  over SMB records decomposed names while the server may store composed ones,
  so a report was not portable between mounts.

### Results tables

The two result tables were narrow slits that could not be made larger.

- **They now grow with the window.** The results split sat inside the same
  stack view as the setup controls, where the extra height of a resized window
  went into the gaps between controls instead of into the tables — so they
  stayed at their minimum whatever the window size. The split now has its own
  container, pinned below the controls and to the bottom of the page. Measured:
  raising the window from 720 to 920 points takes the split from 420 to 519 and
  the project table from 180 to 230.
- **The divider drags.** Both panes hold with equal priority and the position
  is remembered between launches, so the balance between projects and files is
  the operator's choice.
- Each table keeps a 150-point floor rather than 90, the split 420 rather than
  220, and the window opens at 1180x900 with a 900x720 minimum.

### Scan progress

A full archive scan reads every project and backup in full and gave no
indication of how far along it was.

- Discovery reports as it walks. Nothing can be counted until the tree has
  been traversed, which on a large share is minutes of silence.
- The total is measured in **bytes**, not files. Counting files is misleading
  when they range from a few hundred kilobytes to tens of megabytes.
- Progress carries percent complete, bytes done and total, observed rate,
  elapsed time and **estimated time remaining**, so a multi-day scan can be
  planned around.

## 0.11.0 — recovery hardening and application shell

Every defect in this release was found by testing against the real Studio89
archive and by killing transactions mid-flight, not by generated fixtures.
Three of them shared one root cause: code that trusted a recorded status or a
filename where it should have looked at the filesystem.

### Transaction recovery

- **Restore recovers a move interrupted after its rename.** The move loop is
  write-ahead — record `planned`, rename, record `moved`. A process killed
  inside that window leaves the file in quarantine while the state still says
  `planned`, and `restore_session` selected only entries marked `moved`. It
  skipped the entry, left the file in the hidden quarantine directory and
  **exited 0 reporting success**. Twelve SIGKILL trials landed in that window
  seven times: 58% of force quits during a cleanup would have stranded a file.
  Only an in-process exception ran the rollback path, which already resolved
  such entries from the filesystem; a force quit, a lost mount or a power cut
  did not.
- **A killed transaction no longer makes Restore fail permanently.**
  `_atomic_json` wrote through a fixed `<name>.tmp` and refused when that path
  existed. A process killed between the create and the rename left it behind,
  so every later state write refused — including those inside Restore, which
  died *after* moving files back, leaving the session unrecoverable through the
  application. Temporary names are now unique per attempt; the exclusive create
  remains the guard against two writers. The same fixed-name pattern is
  corrected in `publication.py` and `rewrite_profiles.py`.
- **Restore is resumable.** An entry already back at its source with a matching
  digest and nothing in quarantine counts as restored instead of raising
  `Cannot safely restore`. A file in neither place still fails closed.
- Verified under storage failure: a full disk and a volume removed mid-transaction
  both left every file either at its source or in quarantine, never in neither,
  and both recovered completely once the storage was usable.

### Archive classification

- **Never select a backup in a folder that holds an unreadable project.**
  Steinberg numbers saved versions and auto-backups independently and the
  backup-stem matcher strips that number, so `song-02.bak` matched `song.cpr`
  by name even when the unreadable project was `song-01.cpr`. A 0-byte failed
  save is the common shape and the backups beside it are the only record of the
  work that was open at that moment.
- **A backup belongs to the project in its own folder.**
  `find_backup_audio_dir` walks upward, so a backup in a subfolder could be
  adopted by a name-matching project one directory up while the project right
  next to it was never considered. If its own folder holds a project that
  cannot be classified, the backup is kept. `Auto Saves` and `Backups`
  subfolders hold no project and keep using the upward walk.
- Refuse the name-free family fallback when a folder holds more than one
  discovered project. It previously adopted the sole readable project
  regardless of the name evidence.
- **The mandatory 30-day recovery window applies to every quarantine session.**
  It previously applied only when a project had been modified within the last
  three years, leaving the oldest and least reproducible archive material with
  no window at all. The check now runs before any hashing, so an ineligible
  session is refused in milliseconds.
- Name the withheld backups in the backup-policy confirmation, which reported
  how many files were moving but never that any had been excluded, or why.

### Application shell

- Rebuild the main window against the `DAW Project Cleaner.dc.html` design: a
  220pt sidebar replaces the tab strip, carrying the app mark, "Reclaim space,
  safely", the three workspace rows and a "Local processing only / No telemetry"
  footer.
- Move About and a new light/dark switch into trailing title bar accessories,
  and drop the in-content header block and footer privacy line they replace.
- Follow the system appearance until the light/dark switch is used once, then
  remember the choice in `ShellAppearance`.
- Keep all three workspaces built and swap visibility, so a page keeps its
  state while another is on screen.
- Map the design's colour tokens onto macOS semantic colours, so the accent
  colour and Increase Contrast are respected in both palettes. See
  `design/README.md` for the full design-to-AppKit mapping.
- Raise the minimum window size to 900x580 to keep the result tables usable
  beside the fixed-width sidebar.

### Traceability

- `daw-project-cleaner --version`. There was no way to ask a build what it was.
- Every scan report and every quarantine session now records `tool_version`.
  A report authorises a destructive transaction, so it has to name the build
  that produced it; without this a defect found in one version could not be
  traced to the reports it may have produced.

### Distribution safety

- **`scripts/check_public_surface.sh`, run in CI before the tests.** The code
  was always meant to be public and the samples private, but nobody had checked
  the documents. Nine files intended for publication named real client
  projects, server share paths and the studio LAN address, and two leaks were
  worse than that: the personal handover document was tracked, and
  `rewrite_profiles.py` carried a client's project name as a profile label —
  which had already shipped inside the built wheel. Public documents now use
  case codenames; `PROJECT_CONTEXT.md`, `HANDOFF.md`, `work-reports/` and
  `docs/MASS_USE_READINESS.md` are excluded from version control.
- **`scripts/build_package.sh`**, with `--beta` producing a build whose
  permanent deletion is compiled out rather than gated: `PURGE_ENABLED` is
  False, `purge` disappears from the help and refuses with an explanation.
  A beta is versioned `<version>b1` so it can never be confused with a build
  that can delete. The script refuses to package private material.
- `docs/RELEASING.md` records the release checklist and the recall procedure.
  With no telemetry and no update check, recall is manual — which is why the
  beta stays a named beta.
- `docs/SUPPORT.md` rewritten: it promised a GitHub issue tracker that does not
  exist, and asked for exactly the artifacts that should never be sent.

### Command line as a distribution

With no Apple Developer account the application bundle cannot be handed to
anyone else, so the Python package becomes the shape outside users receive.
See `docs/MASS_USE_READINESS.md` §1.

- **Narrow the command line surface to the documented workflow.** `--help`
  listed all 21 subcommands, including internal pilots and research paths such
  as `apply-pilot`, `remote-scan` and `rewrite-validate`, which the application
  deliberately hides. It now lists the eight commands `PRODUCT_WORKFLOW.md`
  describes, each with a one-line description. Nothing is removed and every
  command still runs; `DAW_PROJECT_CLEANER_ADVANCED=1` lists the rest.
- Verified the package end to end: `python -m build` produces a wheel holding
  only the fifteen backend modules with **no third-party dependencies**, the
  sdist carries no `internal-research`, `releases` or `work-reports`, and the
  installed `daw-project-cleaner` console script completes a scan → quarantine
  → restore cycle in a clean virtual environment.

### Operator-facing errors

- **Present an expected refusal as a sentence instead of a stack trace.**
  `main()` had no handler, so every gate in the tool — the whole point of its
  fail-closed design — reached the operator as an unhandled Python traceback,
  and the native app put that traceback straight into an alert. Refusals now
  print `Refused: <reason>` and exit 3; storage failures print
  `Storage error: <reason>` and exit 4. Unexpected exceptions keep their
  traceback, because those are defects and must stay visible.

### Verified, not changed

- Two concurrent cleanups on one folder are safe. The second fails closed with
  `Ambiguous media rollback state`, its session is marked `rollback_failed`, and
  Restore refuses it while the situation is ambiguous, then resolves it
  harmlessly once the file is back. 600 files, none lost or duplicated. There
  is no lock; the safety comes from fail-closed behaviour rather than mutual
  exclusion.
- Apply re-hashes every backup against the report and refuses if anything
  changed since the scan, so a stale report cannot authorise a move.
- A codebase sweep for the "trust the recorded status or the filename" pattern
  that produced three defects in this release found no further instances.
  `_matches_master` also matches on a basename but requires exactly one match
  and refuses otherwise.

### Housekeeping

- Report the same version everywhere. `__init__.py` said 0.6.0 and
  `pyproject.toml` said 0.9.0 while the application said 0.10.0, so a user
  reporting a problem could not say which version they had run.
- Correct `SECURITY.md`, which described 0.4 behaviour and claimed permanent
  purge was hard-disabled when the shipped build permits it behind gates.
- 94 regression tests pass; Swift typecheck clean.

## 0.10.0 — workflow UX

- Expose one user-facing **Scan Folder** action. Complete cross-project and hash
  validation remains automatic, while network transport and diagnostic
  inventory modes are removed from the product surface.
- Organize the native app into **Scan & Review**, **Cleanup** and **Recovery**
  workspaces so read-only discovery, file-changing actions and restoration no
  longer compete in one button-heavy view.
- Keep scan progress, current phase, exact project count and current filename
  visible beside the results instead of hiding work behind a modal state.
- Put infrequently changed backup and exclusion settings behind a remembered
  advanced-options disclosure.
- Stack the locally cached project and selected-project media tables vertically
  for laptop-width windows; retain pagination at 200 projects and 500 media
  rows per page.
- Persist user-controlled window size and position without automatically
  widening the window, while preserving resizing and full-screen support.
- Replace internal terms with outcome-oriented English actions, empty states
  and blockers. Show formats compactly as `Nuendo 15`, `Cubase 12`, etc., with
  the full writer version available as a tooltip.
- Keep every existing backend gate, typed confirmation, quarantine rule,
  authentication check and Restore path unchanged. Swift typecheck and all
  78 generated-fixture tests pass.
- Replace the oversized About alert with a screen-bounded, resizable panel whose
  concise content scrolls independently. Keep purpose, protection, privacy,
  authorship, trademark notice and support details; remove development history.
- Add the standard macOS application menu with About, Hide and **Quit** plus a
  graceful child-process termination path so Dock Quit and Command-Q work.

## 0.9.0 — publication pilot

- Add a read-only publication planner for final-gate CONTROL/CLEANED reports.
- Copy every CLEANED project and uniquely resolved active media file into one
  hidden server-side staging container, verify source and destination SHA-256,
  write a receipt, and reveal the complete batch with one atomic rename.
- Refuse existing destinations, changed sources, links, duplicate Unicode
  names, incomplete physical quarantine, missing/ambiguous active media and
  insufficient same-volume space.
- Add receipt-verified, same-filesystem publication withdrawal and exact
  Restore. Mother-folder retirement remains independently prohibited.
- Add generated-fixture tests for successful publish, destination conflict,
  changed source, interrupted copy cleanup and withdraw/restore round trip.
- Publish the nine validated Case A child projects as 820 files /
  4,807,598,861 bytes. A second full server read verified 820/820 hashes;
  `Vee ja tuule kosjad`, `Lõpulaul` and `Taevased pulmad, võitlus` opened and
  played from the server without missing-media prompts. All 20 original project
  hashes remained unchanged.
- Publish a second seven-project Case A batch as 992 files / 7,700,566,732
  bytes. A second full server read verified 992/992 hashes; direct server opens
  of `Sõja laul` and `Tõrust tammekene` passed. All 20 original project hashes
  remained unchanged.
- Resolve external media only by an explicit, unique, Unicode-normalized exact
  filename supplied by the operator. Reject unused, wrong-name and duplicate
  resolutions; never substitute a similarly named WAV for an active MP3.
- Validate and quarantine the `Linda Itk` controlled copy: preserve 160 active
  media files, including distinct active `Äike.mp3` and `Äike.wav`, and move
  110 Pool-only files / 238,065,544 bytes recoverably.
- Publish `Linda Itk` as a third batch of 161 files / 962,620,427 bytes. An
  independent server reread verified 161/161 hashes and all 20 mother projects
  remained byte-identical. Seventeen child projects are now published; two
  remain blocked on exact active MP3 files and the master remains protected.
- Normalize space-, underscore- and hyphen-separated CONTROL/NORMALIZED/CLEANED
  workflow suffixes when deriving publication folder and project names.
- Expand the generated-fixture suite to 78 passing tests.

## 0.8.1 — safety pilot

- Compare the CLEANED survivor by filesystem identity instead of Unicode path
  spelling when enumerating project artifacts on macOS/APFS.
- Repeat the same inode-level survivor guard during transaction preflight and
  reject duplicate source inodes across a normalization plan.
- Add regression tests for alternate spellings/hard-link aliases of the
  CLEANED project; the full generated-fixture suite passes 66/66.
- Complete the nine copy-ready Case A child-project rehearsals without writing
  to the server mother folder. The final two-project batch retained all 281
  active references and quarantined 195 Pool-only WAV files recoverably.

## 0.8.0 — development

- Add a read-only separation planner for legacy mother folders containing many
  projects and one shared Audio/Edits tree.
- Produce explicit per-project manifests, shared-media duplication cost,
  blockers and a separate fail-closed master-retirement gate.
- Add a copy-only, hash-verified staging rehearsal with free-space checks,
  atomic publication and interruption cleanup; the mother folder is never
  modified and cleanup remains unauthorized.
- Apply the planner to the prior complete Case A audit: 20 projects, nine child
  manifests ready, ten child manifests blocked by missing/ambiguous references,
  and the unsupported-reference master retained.
- Complete the first Case A child pilot over Tailscale: hash-verified staging,
  Cubase 7 to Nuendo 14 Save As, Pool cleanup validation, and recoverable
  quarantine of one unused WAV plus two superseded project artifacts.
- Make CONTROL/CLEANED validation copy and stage names version-neutral so the
  proven Nuendo 14 path is represented accurately alongside Nuendo 15.
- Add normalized batch Apply with all-project preflight, duplicate/shared-source
  rejection and reverse-order Restore of earlier sessions if a later project
  fails. Round-trip and forced-late-failure tests pass.
- Complete the first three-project Case A limited batch on local disposable
  copies: 209 Pool-only WAV files / 392,861,988 bytes plus six superseded
  projects moved into three recoverable sessions; 200 active files remain.

## 0.7.1 — development

- Expose the proven CONTROL/CLEANED normalization validator in the native app.
- Show the exact active-reference, candidate-file, space and old-artifact plan
  before enabling Quarantine Validated Copy.
- Require explicit Nuendo reopen/playback confirmation, a disposable-copy
  warning and typed `QUARANTINE NORMALIZED COPY` confirmation.
- Prefer the just-created session for Restore, remember local same-root
  quarantine locations across launches and keep normalized pilot sessions out
  of the permanent-purge picker.
- Show exact file count, percentage and current filename while a validated
  normalization plan is moved into recoverable quarantine.

## 0.7.0 — development

- Pivot the v1 mass-archive workflow to Nuendo 15 normalization followed by
  Pool cleanup, self-contained archive creation and explicit reopen validation.
- Add a read-only `archive-plan` command that groups projects by shared media,
  blocks missing/ambiguous references and creates a fail-closed Archive Queue.
- Add a cancellable **Build Archive Queue** action to the macOS app with a
  local ready/blocked family summary.
- Validate the queue read-only on the 20-project Case A shared-media archive;
  all projects formed one blocked dependency family and no cleanup was enabled.
- Revalidate the controlled interleaved writer output over the studio LAN in
  Nuendo 15.0.20: no missing-media prompt, retained timeline playback, exact
  three-item Pool, successful save/reopen and parser-verified resave.
- Prepare the first full real-project Nuendo operator pilot from MA OLEN HEA –
  Case F: 75/75 copied files hash-verified, no reference blockers, nine Pool-only
  candidates / 146,919,806 bytes and all server originals left untouched.
- Add a read-only control/cleaned normalization validator. It proves active
  references unchanged, hashes removed Pool media, requires a Nuendo reopen
  confirmation and includes old projects/backups in the recoverable plan so no
  surviving project is left with missing-media references.
- Add a marker-gated DAW-normalized pilot transaction with durable audit state,
  atomic same-filesystem quarantine, reverse-order Restore and interruption
  rollback. The first real Case F copy moved 15 hash-pinned files successfully;
  no file was deleted and all 24 surviving active media paths revalidated.
- Complete the real Case F end-to-end gate: successful Nuendo reopen after media
  quarantine, exact 15-file Restore with full hash verification, fresh
  validation and successful repeat Apply into a new recoverable session.
- Keep cleanup authorization false until every family member completes all
  validation stages.

## 0.6.0 — development

- Added paginated project and media tables: at most 200 project rows and 500
  media rows render at once, while the full inventory remains locally cached.
- Batch live project events into one UI refresh every 500 ms and throttle folder
  progress rendering to prevent the AppKit main thread from being flooded.
- Split Quick Inventory persistence into a full resumable state cache and a
  compact UI snapshot; migrate the earlier combined checkpoint automatically.
- Added a visible activity hierarchy with phase title, progress bar, counters
  and current folder/file instead of overloading one status line.
- Full Safety Scan shows an exact percentage after discovery. Quick Inventory
  uses an indeterminate bar plus honest indexed/queued counts because nested
  folders are still being discovered and the final denominator is unknown.
- Keep project/media page navigation usable during long scans.
- Applied a dedicated GUI/UX critique and loading-state copy review.

## 0.5.9 — development

- Added Remote Quick Inventory for Tailscale/VPN/SMB archives.
- Traverse the archive once and aggregate project, backup and media metadata by
  Audio, Edits, Freeze, Mixdown/Exports and other folder roles.
- Read only a bounded 4096-byte header from main projects for product/version
  inventory; backup files are never opened or hashed in Quick mode.
- Save atomic progress checkpoints with pending/completed directory state and
  resume after Stop, process restart or transient network interruption.
- Added a native scan-mode selector, dynamic queue progress and explicit
  `Apply locked` Quick Inventory summaries.
- Added backend transaction guards that reject all quick or incomplete reports.
- Verified checkpoint and Resume behavior against the Studio89 NAS over
  Tailscale/SMB without writing to the server.

## 0.5.8 — development

- Changed the default backup policy to `Archive Cleanup`: every unambiguously
  classified backup is hashed and selected for quarantine, but backup contents
  are not parsed and do not protect audio media.
- Kept deep backup parsing as explicit Working Project modes: retain all or the
  newest 10, 5, 3 or 1 backups and protect every mapped media reference.
- Archive mode still requires a readable main project, an unambiguous family,
  a regular non-link backup file and a stable SHA-256 before any move.
- Added regression coverage proving Archive Cleanup exposes main-project media
  candidates while Working Project mode retains backup-based protection.

## 0.5.7

- Clarified scans with zero Ready projects but policy-selected backups: the
  final status now shows the backup count, size and exact next action.
- Backup actions now include their counts in `Review Backups (N)…` and
  `Apply Backup Policy (N)…`.
- Exact-writer projects whose candidates are protected by retained backups now
  show `Backup protected` with the protected-reference count instead of the
  vague `Report only` state.

## 0.5.6

- Added two-phase scan visibility: indeterminate project discovery followed by
  an exact `done / total`, percentage and current filename progress display.
- Discover and parse `.bak` files everywhere plus `.cpr`/`.npr` files inside
  `Backup`, `Backups`, `Auto Saves` and `Autosaves` folders. Backup detection
  uses project content rather than trusting the extension alone.
- Added backup retention choices: keep all, 10, 5, 3, 1 or remove all safely
  classified backups. The remembered default is the newest five per project.
- Retained backups protect every locally mapped media reference. Ambiguous,
  unreadable or unmapped backups are always kept and fail closed.
- Added backup review UI with path, size, decision and reason for every backup.
- Added `Apply Backup Policy…`: older backups are moved intact into the shared
  same-filesystem quarantine without rewriting projects or backup contents.
  Restore returns them to their exact original paths.
- Backup-only quarantine sessions use the same 30-day recent-project policy,
  immediate old-project purge authentication, audit and interruption-safe
  persistent state as media cleanup sessions.

## 0.5.5

- Added an editable shared-quarantine selector. Each Mac remembers up to 12
  locations and rediscovers their sessions after restart; offline locations
  remain remembered until the server volume returns.
- Require the quarantine and selected projects to be on the same mounted
  filesystem, preserving atomic moves without duplicate media.
- Restore and permanent deletion now require explicit session selection with
  archive, date, file count, size and status shown in English.
- Added permanent quarantine deletion for projects older than three years,
  protected by macOS owner authentication and an exact typed confirmation.
  Projects modified within the last three years retain a mandatory 30-day
  recovery window.
- Permanent deletion revalidates rewritten projects, project backups, every
  media path, size and SHA-256 before unlinking. Per-file progress is persisted
  so an interrupted purge can be safely resumed.
- Applied a GUI/UX and UX-copy review: clearer hierarchy, compact status text,
  explicit destructive wording and laptop-friendly vertical resizing.

## 0.5.4

- Promoted the exact Nuendo 15.0.30 real Case B Pool topology after Nuendo 15
  open, playback and Save As validation. The promoted signature is limited to
  12 active names, 6 pool-only names, 6 contiguous removal ranges, 7 adjusted
  length fields and 3 shifted references.
- Pinned the source and application-resaved project hashes in the private
  reproducible validation corpus.

## 0.5.3

- Made the main window freely resizable down to laptop-friendly dimensions and
  prevented long scan summaries from expanding it beyond the display.
- Shortened the action controls and compacted Detected format to the Cubase or
  Nuendo product and version; internal container/profile details remain in the
  JSON report.
- Disabled Select Ready when no project is validated instead of showing a modal
  message that could be mistaken for a scan error.

## 0.5.2

- Restore the total Potential-space estimate to the live and completed summary.
- Show the exact Ready count in the Select All Ready button.
- Explain a zero-Ready result instead of making an empty selection look broken.
- Show the selected project's Ready/Report-only reason in the status area.

## 0.5.1 — development

- Stream project rows into the UI as each server project finishes reading.
- Preserve partial read-only rows when a scan is stopped; keep Apply disabled.
- Add per-project checkboxes plus Select All Ready and Deselect All.
- Add selective project Apply with backend-enforced shared-media dependency closure.
- Keep shared candidates visible for review while blocking incomplete rewrite groups.
- Avoid retaining large streamed project-event JSON in the UI process log buffer.

## 0.5.0 — development

- Added application-validated Pool-topology readiness to scan reports.
- Added controlled-copy Apply and automatic last-session Restore to the macOS UI.
- Added warning plus typed confirmation before the UI creates a disposable-copy marker.
- Enforced the application-validated topology gate again inside the transaction backend.
- Kept unknown shapes report-only and permanent deletion disabled.
- Passed a two-project Nuendo 14.0.41 Apply/DAW-open/Restore batch with exact hashes.

## 0.4.0 — development

- Added read-only archive topology audit across Audio, Edits, Freeze and other media locations.
- Added shared-parent project separation planning with ambiguous/missing reference blockers.
- Hard-disabled permanent purge until matching CPR/NPR references can be rewritten and validated.
- Added controlled studio audit and mass-validation/separation protocol.

## 0.3.1 — 2026-08-08

- Scan changes to **Stop Scanning** while discovery is running.
- An empty folder field is rejected instead of resolving to the app's working directory.
- Reworked About text around the final project-consistent cleanup goal and the
  current no-project-rewrite limitation.
- Established a canonical Codex project workspace with private research separation.

## 0.3.0 — 2026-08-08

- Added a custom macOS application icon.
- Added double-confirmed, recoverable quarantine for revalidated review candidates.
- Added session restore and hash-verified permanent deletion of quarantined media.
- Added per-session project backups, durable state and audit logs.
- Kept binary project rewriting disabled; project media references are unchanged.
- Added temporary-directory tests for quarantine, restore, purge and stale-report refusal.

## 0.2.0 — 2026-08-08

- Introduced independent DAW Project Cleaner naming and public-release scope.
- Added product/version and serialization-fingerprint reporting.
- Added read-only RIFF/NUND and RIF2/NUND archive scanning.
- Added historical read coverage from Cubase 5 through Nuendo 15.
- Added candidate space estimates with cross-project safety guards.
- Removed all automatic file movement and project-writing actions.
- Moved reports to macOS Application Support.
- Added Studio89 attribution, privacy notice and voluntary support QR/link.
- Added public legal, security, safety, build and contribution documentation.
