# Canonical workspace

This directory (`~/Desktop/JARVIS/DAW Project Cleaner`) is the canonical
workspace for all future DAW Project Cleaner development, as of 2026-08-18.
The former `~/Documents/Codex/DAW-Project-Cleaner` folder is superseded; it
still holds the bulky staged project copies and fixture audio that were
deliberately not carried over. Start from `HANDOFF.md`.

## Safety invariants

- Never test moves or deletion on real projects, server archives or user audio.
- Use generated fixtures inside temporary directories for destructive tests.
- Scan is read-only and must remain cancellable.
- Fail closed on parse errors, changed hashes, ambiguous paths and symlinks.
- Quarantine must precede permanent deletion and remain restorable.
- Do not claim project/file consistency while CPR/NPR references are not removed.
- Binary project rewriting stays disabled until validated by supported format
  profile with application open, playback and resave tests.

## Repository hygiene

- Public code and documentation live at the project root.
- `internal-research/` contains private samples, derived scans and experimental
  historical work; never include it in a public repository or release archive.
- `releases/` contains local packaged builds and is not source-controlled.
