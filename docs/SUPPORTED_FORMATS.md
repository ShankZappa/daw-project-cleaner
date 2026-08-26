# Supported formats

## Read support

DAW Project Cleaner recognizes the inspected `NUND` project-container families:

- `RIFF` with 32-bit big-endian container/chunk lengths;
- `RIF2` with 64-bit big-endian container/chunk lengths.

The reader validates the main arrangement, project-pool boundary, structured
audio-name fields and a serialization fingerprint. The extension `.cpr` or
`.npr` is used for discovery only.

## Tested archive range

Private, user-owned read-only validation has included:

- Cubase 5.1, 5.5, 7.0, 7.5, 9.5, 10.0, 11.0 and 12.0;
- Nuendo 11, 12, 13, 14 and 15;
- both `.cpr` and `.npr` extensions;
- both RIFF/32 and RIF2/64 containers;
- projects with audio, pool-side-only media and MIDI-only arrangements.

No private corpus is distributed with this repository.

## Fingerprints

The app reports a compact fingerprint such as:

`RIFF32/chunks14/PAv3/MRv6/PPv3/GTv2/GEv3`

This records the outer container width, top-level chunk count and selected
serialized class generations. It is intended for diagnostics and fail-closed
compatibility routing—not as a complete public specification.

## Unsupported or limited cases

- unknown container forms or malformed length tables;
- projects with multiple or unrecognized main pool layouts;
- media extensions outside the documented allowlist;
- ambiguous duplicate basenames within an Audio tree;
- external media stored outside a uniquely detected sibling Audio folder;
- cloud placeholders, permissions errors and filesystem links;
- unrestricted project rewriting or format conversion.

Unknown cases remain report-only or produce an explicit error. The parser does
not infer compatibility from the application version alone.

## Controlled-copy Apply profiles

Version 0.5 exposes Apply only for application-validated topology cohorts under
the pinned Nuendo 14.0.41, Nuendo 15.0.30 and Cubase 12.0.70 fingerprints.
Ready status additionally requires the validated active/Pool item counts,
serialized deletion-range arrangement, aggregate length/reference pattern and
complete local media mapping. Other projects from the same application version
remain Report only. This is a disposable-copy pilot, not general write support.
