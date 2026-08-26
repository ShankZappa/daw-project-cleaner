# Project rewrite validation and promotion gate

Project writers are selected by the complete product/version/container/class
fingerprint, never by extension or major version alone. A mismatch refuses to
write. Inputs are immutable and generated projects exist only as new files.

## Automated checks

- corpus input and official-cleaned SHA-256 match pinned values;
- complete RIFF/RIF2 container and chunk coverage parse successfully;
- product, exact version and serialization fingerprint remain unchanged;
- active media names remain unchanged;
- all intended pool-only names disappear and no removed UTF-8 name survives;
- project-generated audit hash matches the output bytes;
- retained PPool/GTree prefix matches the DAW-cleaned control where applicable;
- a pinned application-resaved output reopens with the same active/pool state.

## Promotion states

- **blocked** — any automated check fails;
- **structural-only** — binary checks pass but the generated output lacks an
  exact-application open/playback/resave/reopen proof;
- **application-validated-pilot** — structural checks and pinned application
  resave evidence pass;
- **production** — not currently available; additionally requires varied pool
  shapes, multiple active items, edits/freeze/external media cases, transactional
  backup/restore and a limited disposable copy-only batch pilot. A single-project
  Nuendo 15 interleaved transaction and exact restore has passed; the limited
  homogeneous batch and non-Audio media cases remain outstanding.

An application-validated-pilot profile may generate a new project copy for a
controlled local test. It does not authorize server cleanup, media deletion or
permanent purge.

## Current registry

- Nuendo 14.0.41 RIF264/chunks14/PAv4/MRv6/PPv5/GTv2/GEv3:
  one structural-only case and two application-validated cases, including the
  real large-Pool Case B shape.
- Cubase 12.0.70 RIFF32/chunks14/PAv3/MRv6/PPv3/GTv2/GEv3:
  one application-validated two-unused case.
- Nuendo 15.0.30: controlled pair and exact-profile writer pass all structural
  checks; generated output SHA-256 is
  `a00553b3f8f3dfaa5e74aa461a23d9562308932f849454b2d5fd9ba0f54aab8d`.
  The project opened, played, accepted a playback-routing change, resaved and
  reopened in Nuendo 15.0.30. Pinned resave SHA-256:
  `fda6782dd6428d9a49783fc69c35167cf60f4adcc13038e06321d8578ba7827e`.
  Status: application-validated-pilot for the exact one-active/two-unused Pool
  shape.
- Nuendo 15.0.30 multi-active: a second controlled pair retains three active
  Pool items while removing three pool-only items. It confirms child count
  6 -> 3, one contiguous 2361-byte removed branch, eight adjusted length fields
  and three shifted object references. Generated SHA-256:
  `afe8828d02fe57b8b58b86c41c3d829f47c59b4007989472d7c56cd4c9d12c0e`.
  It opened, played, retained the intended timeline events and Pool state,
  resaved and reopened in Nuendo 15.0.30. Pinned resave SHA-256:
  `fd706bb258f679f0e048de01354aed7cf4a06df2aad6c6292ecd84531484a883`.
  Status: application-validated-pilot.
- Nuendo 15.0.30 interleaved: active and pool-only sibling records alternate in
  serialized Pool order. The writer removes three separate 789-byte spans,
  retains all three active records and adjusts eight aggregate lengths plus
  three later object references. Generated SHA-256:
  `50cb13bddd2d53a2c2b3362911cc69a2915c852c98e9fdfc62126cfd1bdb5ac0`.
  It opened, played all retained events, preserved the intended Pool state,
  resaved and reopened in Nuendo 15.0.30. Pinned resave SHA-256:
  `dcf4d2136b5132880b7db263f602c13bb377b8dce8c85e368e222e147a2feb67`.
  A second studio-LAN application validation on 2026-08-12 opened the generated
  15.0.30 project in Nuendo 15.0.20 without a missing-media prompt, played all
  three retained timeline events, showed only those three Pool items, saved and
  reopened successfully. The 15.0.20 resave SHA-256 is
  `f4f95a21f4de4b59a03a8672d8338331e59e77e3f49ec0569c38a0a0c4473d5d`.
  This is evidence for the exact controlled shape across those patch releases;
  it is not a general claim that Nuendo projects can be safely downgraded.
  Status: application-validated-pilot.
- Nuendo 14.0.41 real Pool: a migrated Case B control/clean pair validates the
  large layout where pool-only siblings appear after Audio/Clip Packages/Video
  and before Trash/Media. The writer removes six spans totalling 50,197 bytes,
  keeps the 11-child retained Audio tree count unchanged, adjusts seven lengths
  and shifts three later references. Generated SHA-256:
  `a19dd640f8659073b20f15493680298cfdd873cdc68edd6d15da62ec898f6d3f`.
  It opened, played, retained the intended Pool state, resaved and reopened in
  Nuendo 14.0.41. Pinned resave SHA-256:
  `6c49a1bd5dfea8093a2834f3623fc209f1bc4c799a26aee602c8d2340014a2d9`.
  Status: application-validated-pilot.

The machine-readable report is generated with:

```bash
python3 -m daw_project_cleaner.cli rewrite-validate \
  internal-research/format-pairs \
  --report internal-research/analysis/rewrite-validation.json
```
