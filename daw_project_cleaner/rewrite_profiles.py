"""Quarantined exact-profile project rewrite candidates.

This is intentionally not connected to the production or GUI Apply workflow.
It is based on controlled before/control/cleaned differential projects. The
transaction module may use it only in the marker-gated disposable-copy pilot.
A generated project must be validated by opening and resaving it in the exact
matching Cubase/Nuendo version before a profile can be promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import uuid
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .format import ParsedProject, parse_project


NUENDO_14_PROFILE = "RIF264/chunks14/PAv4/MRv6/PPv5/GTv2/GEv3"
NUENDO_15_PROFILE = NUENDO_14_PROFILE
SUPPORTED_NUENDO_RIF2_VERSIONS = {"14.0.41", "15.0.30"}
CUBASE_12_PROFILE = "RIFF32/chunks14/PAv3/MRv6/PPv3/GTv2/GEv3"


class ExperimentalRewriteError(ValueError):
    pass


@dataclass
class RewriteAudit:
    source_sha256: str
    output_sha256: str
    delete_start: int
    delete_end: int
    deleted_bytes: int
    pool_only_names: List[str]
    length_fields: List[int]
    reference_fields: List[int]
    delete_ranges: List[Tuple[int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class ValidatedRewriteShape:
    product: str
    version: str
    container: str
    serialization_profile: str
    active_names: int
    pool_only_names: int
    delete_ranges: int
    length_fields: int
    reference_fields: int
    contiguous_ranges: bool
    label: str


APPLICATION_VALIDATED_SHAPES = (
    ValidatedRewriteShape(
        "Nuendo", "14.0.41", "RIF2", NUENDO_14_PROFILE,
        1, 2, 2, 8, 3, True, "Nuendo 14 native two-unused",
    ),
    ValidatedRewriteShape(
        "Nuendo", "14.0.41", "RIF2", NUENDO_14_PROFILE,
        12, 6, 6, 7, 3, True, "Nuendo 14 real large-Pool case B",
    ),
    ValidatedRewriteShape(
        "Cubase", "12.0.70", "RIFF", CUBASE_12_PROFILE,
        1, 2, 1, 8, 3, True, "Cubase 12 native two-unused",
    ),
    ValidatedRewriteShape(
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        1, 2, 2, 8, 3, True, "Nuendo 15 native two-unused",
    ),
    ValidatedRewriteShape(
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        3, 3, 3, 8, 3, True, "Nuendo 15 multi-active",
    ),
    ValidatedRewriteShape(
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        3, 3, 3, 8, 3, False, "Nuendo 15 interleaved",
    ),
    ValidatedRewriteShape(
        "Nuendo", "15.0.30", "RIF2", NUENDO_15_PROFILE,
        12, 6, 6, 7, 3, True, "Nuendo 15 real large-Pool case B",
    ),
)


def application_validated_shape_label(
    parsed: ParsedProject, audit: RewriteAudit
) -> Optional[str]:
    """Return the promoted topology label, never just a version match."""
    active = sum(
        bool(offsets) and any(offset < parsed.pool_offset for offset in offsets)
        for offsets in parsed.occurrences.values()
    )
    pool_only = sum(
        bool(offsets) and all(offset > parsed.pool_offset for offset in offsets)
        for offsets in parsed.occurrences.values()
    )
    contiguous = all(
        left_end == right_start
        for (_, left_end), (right_start, _) in zip(
            audit.delete_ranges, audit.delete_ranges[1:]
        )
    )
    signature = (
        parsed.product, parsed.version, parsed.container,
        parsed.serialization_profile, active, pool_only,
        len(audit.delete_ranges), len(audit.length_fields),
        len(audit.reference_fields), contiguous,
    )
    for shape in APPLICATION_VALIDATED_SHAPES:
        expected = (
            shape.product, shape.version, shape.container,
            shape.serialization_profile, shape.active_names,
            shape.pool_only_names, shape.delete_ranges,
            shape.length_fields, shape.reference_fields,
            shape.contiguous_ranges,
        )
        if signature == expected:
            return shape.label
    return None


def _text_field_token(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">I", len(raw) + 4) + raw + b"\x00\xef\xbb\xbf"


def _all(data: bytes, needle: bytes, start: int, end: int) -> List[int]:
    result: List[int] = []
    cursor = start
    while True:
        found = data.find(needle, cursor, end)
        if found < 0:
            return result
        result.append(found)
        cursor = found + 1


def _object_length_offset(data: bytes, name: str, start: int, end: int) -> int:
    raw = name.encode("ascii") + b"\x00"
    marker = struct.pack(">I", len(raw)) + raw
    hits = _all(data, marker, start, end)
    if len(hits) != 1:
        raise ExperimentalRewriteError(
            f"Expected one serialized {name} object, found {len(hits)}"
        )
    # Two bytes of class version follow the length-prefixed class name in the
    # Nuendo 14.0.41 archive profile.
    offset = hits[0] + len(marker) + 2
    if offset + 8 > end:
        raise ExperimentalRewriteError(f"Truncated {name} length field")
    return offset


def _object_length_offset_32(data: bytes, name: str, start: int, end: int) -> int:
    raw = name.encode("ascii") + b"\x00"
    marker = struct.pack(">I", len(raw)) + raw
    hits = _all(data, marker, start, end)
    if len(hits) != 1:
        raise ExperimentalRewriteError(
            f"Expected one serialized {name} object, found {len(hits)}"
        )
    offset = hits[0] + len(marker) + 2
    if offset + 4 > end:
        raise ExperimentalRewriteError(f"Truncated {name} length field")
    return offset


def _find_category_audio(data: bytes, start: int, end: int) -> int:
    audio = _text_field_token("Audio")
    required = [
        _text_field_token("Clip Packages"),
        _text_field_token("Video"),
        _text_field_token("Trash"),
        _text_field_token("Media"),
    ]
    candidates = _all(data, audio, start, end)
    valid: List[int] = []
    for prefix in candidates:
        cursor = prefix + len(audio)
        ok = True
        for token in required:
            found = data.find(token, cursor, min(end, cursor + 160))
            if found < 0:
                ok = False
                break
            cursor = found + len(token)
        if ok:
            valid.append(prefix)
    if len(valid) != 1:
        raise ExperimentalRewriteError(
            f"Expected one pool category sequence, found {len(valid)}"
        )
    return valid[0]


def _find_nuendo_category_markers(
    data: bytes, start: int, end: int
) -> Tuple[int, int, int, int, int]:
    """Locate the unique Audio/Clip/Video ... Trash/Media category chain."""
    audio_token = _text_field_token("Audio")
    clip_token = _text_field_token("Clip Packages")
    video_token = _text_field_token("Video")
    trash_token = _text_field_token("Trash")
    media_token = _text_field_token("Media")
    valid: List[Tuple[int, int, int, int, int]] = []
    for audio in _all(data, audio_token, start, end):
        clip = data.find(
            clip_token, audio + len(audio_token),
            min(end, audio + len(audio_token) + 160),
        )
        if clip < 0:
            continue
        video = data.find(
            video_token, clip + len(clip_token),
            min(end, clip + len(clip_token) + 160),
        )
        if video < 0:
            continue
        trash = data.find(trash_token, video + len(video_token), end)
        if trash < 0:
            continue
        media = data.find(
            media_token, trash + len(trash_token),
            min(end, trash + len(trash_token) + 160),
        )
        if media >= 0:
            valid.append((audio, clip, video, trash, media))
    if len(valid) != 1:
        raise ExperimentalRewriteError(
            f"Expected one Nuendo pool category chain, found {len(valid)}"
        )
    return valid[0]


def _find_category_audio_cubase12(data: bytes, start: int, end: int) -> int:
    audio = _text_field_token("Audio")
    required = [
        _text_field_token("Video"),
        _text_field_token("Trash"),
        _text_field_token("Media"),
    ]
    valid: List[int] = []
    for prefix in _all(data, audio, start, end):
        cursor = prefix + len(audio)
        for token in required:
            found = data.find(token, cursor, min(end, cursor + 128))
            if found < 0:
                break
            cursor = found + len(token)
        else:
            valid.append(prefix)
    if len(valid) != 1:
        raise ExperimentalRewriteError(
            f"Expected one Cubase 12 pool category sequence, found {len(valid)}"
        )
    return valid[0]


def _find_unused_branch_start(
    data: bytes,
    pool_offset: int,
    category_audio: int,
    pool_only_names: Sequence[str],
) -> int:
    stems = sorted({Path(name).stem for name in pool_only_names})
    label_offsets: List[int] = []
    for stem in stems:
        token = _text_field_token(stem)
        hits = _all(data, token, pool_offset, category_audio)
        if not hits:
            raise ExperimentalRewriteError(
                f"Pool-tree label for {stem!r} was not found"
            )
        # The stem can reappear in the later media descriptor. The first valid
        # field after PPool is the GTree label whose edge begins 32 bytes prior.
        label_offsets.append(min(hits) + 4)
    first_label = min(label_offsets)
    # The serialized edge begins 36 bytes before the label text: 32 bytes of
    # edge/reference data followed by the label's four-byte string length.
    start = first_label - 36
    if start <= pool_offset or start >= category_audio:
        raise ExperimentalRewriteError("Derived unused-branch boundary is invalid")
    return start


def _require_trailing_unused_branch(
    data: bytes,
    pool_offset: int,
    category_audio: int,
    delete_start: int,
    active_names: Sequence[str],
) -> None:
    """Prove that no retained Pool-tree label occurs in the deletion span.

    The first Nuendo corpus pairs happened to serialize every pool-only item as
    one trailing branch. A later controlled pair showed that import order can
    interleave retained and unused siblings. Deleting from the first unused
    label through the Audio-category marker would then silently remove retained
    Pool-tree entries even though arrangement-side filename checks still pass.
    """
    retained_after_boundary: List[str] = []
    for name in sorted(set(active_names)):
        stem = Path(name).stem
        hits = _all(
            data, _text_field_token(stem), pool_offset, category_audio
        )
        if not hits:
            raise ExperimentalRewriteError(
                f"Retained Pool-tree label for {stem!r} was not found"
            )
        if min(hits) >= delete_start:
            retained_after_boundary.append(name)
    if retained_after_boundary:
        raise ExperimentalRewriteError(
            "Pool-only entries are interleaved with retained entries; "
            "multi-span rewrite is not validated: "
            + ", ".join(retained_after_boundary)
        )


def _nuendo_unused_item_ranges(
    data: bytes,
    pool_offset: int,
    category_audio: int,
    active_names: Sequence[str],
    pool_only_names: Sequence[str],
) -> List[Tuple[int, int]]:
    """Return proven serialized sibling spans for pool-only Nuendo items.

    In the validated RIF2 GTree profile, a retained sibling's reference begins
    30 bytes before its first tree-label token and a pool-only sibling's
    reference begins 32 bytes before that token. The four zero bytes preceding
    a reference are shared serialization padding: deleting from one reference
    through the next reference preserves exactly one padding prefix.
    """
    # A converted import can expose both original and converted extensions for
    # one serialized Pool item (for example UNUSED.mp3 and UNUSED.wav). The
    # GTree key is the shared stem, so collapse same-side variants by stem but
    # refuse a stem that crosses the active/pool-only boundary.
    active_stems = {Path(name).stem for name in active_names}
    unused_stems = {Path(name).stem for name in pool_only_names}
    overlap = sorted(active_stems & unused_stems)
    if overlap:
        raise ExperimentalRewriteError(
            "Active and pool-only media share Pool stems: " + ", ".join(overlap)
        )

    items: List[Tuple[int, bool, str]] = []
    for unused, stems in ((False, active_stems), (True, unused_stems)):
        for stem in sorted(stems):
            hits = _all(
                data, _text_field_token(stem), pool_offset, category_audio
            )
            if not hits:
                raise ExperimentalRewriteError(
                    f"Pool-tree label for {stem!r} was not found"
                )
            label = min(hits)
            reference = label - (32 if unused else 30)
            if reference <= pool_offset or reference + 8 > category_audio:
                raise ExperimentalRewriteError(
                    f"Derived Pool sibling boundary for {stem!r} is invalid"
                )
            word = struct.unpack(">Q", data[reference:reference + 8])[0]
            if not (word & (1 << 63)):
                raise ExperimentalRewriteError(
                    f"Pool sibling for {stem!r} lacks a marked object reference"
                )
            items.append((reference, unused, stem))

    items.sort()
    if len({offset for offset, _unused, _name in items}) != len(items):
        raise ExperimentalRewriteError("Pool sibling boundaries are not unique")
    ranges: List[Tuple[int, int]] = []
    for index, (start, unused, _name) in enumerate(items):
        if not unused:
            continue
        end = items[index + 1][0] if index + 1 < len(items) else category_audio
        if end - start < 64:
            raise ExperimentalRewriteError(
                "Derived pool-only sibling span is implausibly small"
            )
        ranges.append((start, end))
    if not ranges:
        raise ExperimentalRewriteError("No pool-only sibling spans were derived")
    return ranges


def _nuendo_post_category_unused_ranges(
    data: bytes,
    region_start: int,
    region_end: int,
    active_names: Sequence[str],
    pool_only_names: Sequence[str],
) -> List[Tuple[int, int]]:
    """Derive unused sibling spans serialized between Video and Trash."""
    active_stems = {Path(name).stem for name in active_names}
    unused_stems = {Path(name).stem for name in pool_only_names}
    overlap = sorted(active_stems & unused_stems)
    if overlap:
        raise ExperimentalRewriteError(
            "Active and pool-only media share Pool stems: " + ", ".join(overlap)
        )
    retained_in_region = []
    for stem in sorted(active_stems):
        if _all(data, _text_field_token(stem), region_start, region_end):
            retained_in_region.append(stem)
    if retained_in_region:
        raise ExperimentalRewriteError(
            "Retained Pool labels occur inside the post-category unused region: "
            + ", ".join(retained_in_region)
        )

    starts: List[int] = []
    for stem in sorted(unused_stems):
        hits = _all(data, _text_field_token(stem), region_start, region_end)
        if not hits:
            raise ExperimentalRewriteError(
                f"Post-category Pool label for {stem!r} was not found"
            )
        reference = min(hits) - 32
        if reference < region_start or reference + 8 > region_end:
            raise ExperimentalRewriteError(
                f"Post-category sibling boundary for {stem!r} is invalid"
            )
        word = struct.unpack(">Q", data[reference:reference + 8])[0]
        if not (word & (1 << 63)):
            raise ExperimentalRewriteError(
                f"Post-category sibling for {stem!r} lacks an object reference"
            )
        starts.append(reference)
    starts.sort()
    if len(set(starts)) != len(unused_stems):
        raise ExperimentalRewriteError(
            "Post-category Pool sibling boundaries are not unique"
        )
    ranges = [
        (start, starts[index + 1] if index + 1 < len(starts) else region_end)
        for index, start in enumerate(starts)
    ]
    if any(end - start < 64 for start, end in ranges):
        raise ExperimentalRewriteError(
            "Derived post-category pool-only span is implausibly small"
        )
    return ranges


def _find_unused_branch_start_32(
    data: bytes,
    pool_offset: int,
    category_audio: int,
    pool_only_names: Sequence[str],
) -> int:
    stems = sorted({Path(name).stem for name in pool_only_names})
    label_prefixes: List[int] = []
    for stem in stems:
        hits = _all(data, _text_field_token(stem), pool_offset, category_audio)
        if not hits:
            raise ExperimentalRewriteError(
                f"Pool-tree label for {stem!r} was not found"
            )
        label_prefixes.append(min(hits))
    # The RIFF/32-bit GTree edge begins 16 bytes before its label prefix.
    start = min(label_prefixes) - 16
    if start <= pool_offset or start >= category_audio:
        raise ExperimentalRewriteError("Derived 32-bit unused-branch boundary is invalid")
    return start


def _arrangement_arch(parsed) -> object:
    roots = [
        (index, chunk) for index, chunk in enumerate(parsed.chunks)
        if chunk.tag == "ROOT" and chunk.class_name == "PArrangement"
    ]
    if len(roots) != 1:
        raise ExperimentalRewriteError("Arrangement ROOT could not be identified")
    index, _root = roots[0]
    if index + 1 >= len(parsed.chunks) or parsed.chunks[index + 1].tag != "ARCH":
        raise ExperimentalRewriteError("Arrangement ROOT is not followed by ARCH")
    return parsed.chunks[index + 1]


def rewrite_remove_pool_only(source: Path) -> Tuple[bytes, RewriteAudit]:
    source = source.resolve(strict=True)
    data = source.read_bytes()
    parsed = parse_project(source)
    if (
        parsed.product != "Nuendo" or parsed.container != "RIF2" or
        parsed.version not in SUPPORTED_NUENDO_RIF2_VERSIONS or
        parsed.serialization_profile != NUENDO_14_PROFILE
    ):
        raise ExperimentalRewriteError(
            "Writer requires a registered exact Nuendo RIF2 version and profile " + NUENDO_14_PROFILE
        )
    arrangement = _arrangement_arch(parsed)
    if arrangement is None or not (arrangement.payload_offset < parsed.pool_offset < arrangement.end):
        raise ExperimentalRewriteError("Arrangement ARCH could not be identified")

    pool_only = sorted(
        name for name, offsets in parsed.occurrences.items()
        if offsets and all(offset > parsed.pool_offset for offset in offsets)
    )
    if not pool_only:
        raise ExperimentalRewriteError("Project has no pool-only audio evidence")
    active_names = sorted(
        name for name, offsets in parsed.occurrences.items()
        if offsets and any(offset < parsed.pool_offset for offset in offsets)
    )
    audio_category, _clip_category, video_category, trash_category, _media_category = (
        _find_nuendo_category_markers(
            data, parsed.pool_offset, arrangement.end
        )
    )
    first_unused_label = min(
        min(_all(
            data, _text_field_token(Path(name).stem),
            parsed.pool_offset, arrangement.end,
        ))
        for name in pool_only
    )
    if first_unused_label < audio_category:
        layout = "pre_categories"
        tree_boundary = audio_category
        delete_ranges = _nuendo_unused_item_ranges(
            data, parsed.pool_offset, tree_boundary, active_names, pool_only
        )
    elif video_category < first_unused_label < trash_category:
        layout = "post_video"
        tree_boundary = trash_category
        delete_ranges = _nuendo_post_category_unused_ranges(
            data, video_category + len(_text_field_token("Video")),
            tree_boundary, active_names, pool_only,
        )
    else:
        raise ExperimentalRewriteError(
            "Pool-only labels do not match a validated Nuendo category layout"
        )
    delete_start = min(start for start, _end in delete_ranges)
    delete_end = max(end for _start, end in delete_ranges)
    delta = sum(end - start for start, end in delete_ranges)
    if delta < 64:
        raise ExperimentalRewriteError("Derived unused spans are implausibly small")

    length_offsets = [
        4,  # RIF2 payload
        arrangement.offset + 4,  # Arrangement ARCH payload
        _object_length_offset(data, "PArrangement", arrangement.payload_offset, parsed.pool_offset),
        _object_length_offset(data, "MRoot", arrangement.payload_offset, parsed.pool_offset),
        _object_length_offset(data, "PPool", parsed.pool_offset - 4, delete_start),
        _object_length_offset(data, "GTree", parsed.pool_offset, delete_start),
        _object_length_offset(data, "GTreeEntry", parsed.pool_offset, delete_start),
    ]
    entry_length = length_offsets[-1]
    entry_payload = entry_length + 8
    nested_length = entry_payload + 22
    if layout == "pre_categories":
        # In the pre-category layout the removed sibling branch is inside this
        # nested span. In the real post-Video layout it is outside the span and
        # the official Nuendo 14 pair confirms the nested length is unchanged.
        length_offsets.append(nested_length)

    unused_stems = {Path(name).stem for name in pool_only}
    child_count_offset = entry_payload + 40
    child_count = struct.unpack(">I", data[child_count_offset:child_count_offset + 4])[0]
    discriminator_offset = entry_payload + 68

    mutable = bytearray(data)
    for offset in length_offsets:
        if offset >= delete_start or offset + 8 > len(mutable):
            raise ExperimentalRewriteError(f"Unsafe length field at 0x{offset:x}")
        old = struct.unpack(">Q", mutable[offset:offset + 8])[0]
        if old < delta:
            raise ExperimentalRewriteError(
                f"Length at 0x{offset:x} is smaller than removal"
            )
        mutable[offset:offset + 8] = struct.pack(">Q", old - delta)

    if layout == "post_video":
        # This exact real-world Nuendo 14 shape keeps the 11 retained Audio-tree
        # children unchanged; pool-only media is serialized in a separate
        # branch after Video and is not included in this count.
        validated_real_pool_shape = (
            parsed.version in {"14.0.41", "15.0.30"} and child_count == 11
        )
        if not validated_real_pool_shape:
            raise ExperimentalRewriteError(
                "Post-Video writer is validated only for the application-tested "
                "11-child real-Pool shape"
            )
        if mutable[discriminator_offset] != 0x02:
            raise ExperimentalRewriteError(
                "Unexpected post-Video Nuendo 14 retained-tree discriminator"
            )
    else:
        retained_count = child_count - len(unused_stems)
        if retained_count < 1:
            raise ExperimentalRewriteError("Rewrite would retain no active pool items")
        mutable[child_count_offset:child_count_offset + 4] = struct.pack(
            ">I", retained_count
        )
    if layout == "pre_categories" and parsed.version == "14.0.41":
        # Only the one-retained-item Nuendo 14 shape has an application-tested
        # corpus pair. Do not extrapolate the tree discriminator beyond it.
        if retained_count != 1:
            raise ExperimentalRewriteError(
                "Nuendo 14 writer requires exactly one retained pool item"
            )
        if mutable[discriminator_offset] != 0x02:
            raise ExperimentalRewriteError("Unexpected Nuendo 14 GTreeEntry discriminator")
        mutable[discriminator_offset] = 0x03
    elif layout == "pre_categories" and parsed.version == "15.0.30":
        # Exact controlled pairs currently validate two Nuendo 15 tree shapes:
        # one retained item uses discriminator 3, while three retained items
        # use discriminator 2. Refuse every unobserved shape.
        expected_discriminator = {1: 0x03, 3: 0x02}.get(retained_count)
        if expected_discriminator is None:
            raise ExperimentalRewriteError(
                f"Nuendo 15 writer has no validated tree rule for "
                f"{retained_count} retained pool items"
            )
        if mutable[discriminator_offset] != expected_discriminator:
            raise ExperimentalRewriteError("Unexpected Nuendo 15 GTreeEntry discriminator")
    elif layout == "pre_categories":
        raise ExperimentalRewriteError("No discriminator rule for this Nuendo version")

    # RIF2 object references use the high bit as a reference marker and the
    # lower 63 bits as an archive/file position in the inspected profile.
    # Update only plausible references that point beyond the removed branch.
    reference_offsets: List[int] = []
    cursor = tree_boundary
    while cursor <= arrangement.end - 8:
        if mutable[cursor] == 0x80:
            word = struct.unpack(">Q", mutable[cursor:cursor + 8])[0]
            target = word & ((1 << 63) - 1)
            if tree_boundary <= target < arrangement.end:
                mutable[cursor:cursor + 8] = struct.pack(
                    ">Q", (1 << 63) | (target - delta)
                )
                reference_offsets.append(cursor)
                cursor += 8
                continue
        cursor += 1
    if not reference_offsets:
        raise ExperimentalRewriteError("No shifted object references were found")

    for start, end in reversed(delete_ranges):
        del mutable[start:end]
    output = bytes(mutable)
    # Validate the complete outer container and ensure removed names vanished.
    declared = struct.unpack(">Q", output[4:12])[0]
    if declared != len(output) - 16:
        raise ExperimentalRewriteError("Generated RIF2 length does not validate")
    for name in pool_only:
        if name.encode("utf-8") in output:
            raise ExperimentalRewriteError(f"Generated data still contains {name}")

    audit = RewriteAudit(
        source_sha256=hashlib.sha256(data).hexdigest(),
        output_sha256=hashlib.sha256(output).hexdigest(),
        delete_start=delete_start,
        delete_end=delete_end,
        deleted_bytes=delta,
        pool_only_names=pool_only,
        length_fields=length_offsets,
        reference_fields=reference_offsets,
        delete_ranges=delete_ranges,
    )
    return output, audit


def rewrite_remove_pool_only_cubase12(source: Path) -> Tuple[bytes, RewriteAudit]:
    """Rewrite only the controlled Cubase 12.0.70 RIFF pool-tree profile."""
    source = source.resolve(strict=True)
    data = source.read_bytes()
    parsed = parse_project(source)
    if (
        parsed.product != "Cubase" or parsed.container != "RIFF" or
        parsed.version != "12.0.70" or parsed.serialization_profile != CUBASE_12_PROFILE
    ):
        raise ExperimentalRewriteError(
            "Writer requires exact Cubase 12.0.70 profile " + CUBASE_12_PROFILE
        )
    arrangement = _arrangement_arch(parsed)
    if not (arrangement.payload_offset < parsed.pool_offset < arrangement.end):
        raise ExperimentalRewriteError("Arrangement ARCH could not be identified")

    pool_only = sorted(
        name for name, offsets in parsed.occurrences.items()
        if offsets and all(offset > parsed.pool_offset for offset in offsets)
    )
    if not pool_only:
        raise ExperimentalRewriteError("Project has no pool-only audio evidence")
    category_audio = _find_category_audio_cubase12(
        data, parsed.pool_offset, arrangement.end
    )
    delete_start = _find_unused_branch_start_32(
        data, parsed.pool_offset, category_audio, pool_only
    )
    active_names = sorted(
        name for name, offsets in parsed.occurrences.items()
        if offsets and any(offset < parsed.pool_offset for offset in offsets)
    )
    _require_trailing_unused_branch(
        data, parsed.pool_offset, category_audio, delete_start, active_names
    )
    delete_end = category_audio
    delta = delete_end - delete_start
    if delta < 64:
        raise ExperimentalRewriteError("Derived unused branch is implausibly small")

    length_offsets = [
        4,  # RIFF payload
        arrangement.offset + 4,  # Arrangement ARCH payload
        _object_length_offset_32(
            data, "PArrangement", arrangement.payload_offset, parsed.pool_offset
        ),
        _object_length_offset_32(
            data, "MRoot", arrangement.payload_offset, parsed.pool_offset
        ),
        _object_length_offset_32(data, "PPool", parsed.pool_offset - 4, delete_start),
        _object_length_offset_32(data, "GTree", parsed.pool_offset, delete_start),
        _object_length_offset_32(
            data, "GTreeEntry", parsed.pool_offset, delete_start
        ),
    ]
    entry_length = length_offsets[-1]
    entry_payload = entry_length + 4
    # In the 32-bit Cubase 12 archive the nested span is 14 bytes into the
    # GTreeEntry payload; the controlled pair changes it by exactly the branch
    # size, just like the corresponding 64-bit field in Nuendo 14.
    length_offsets.append(entry_payload + 14)
    child_count_offset = entry_payload + 24
    child_count = struct.unpack(
        ">I", data[child_count_offset:child_count_offset + 4]
    )[0]
    unused_stems = {Path(name).stem for name in pool_only}
    if child_count - len(unused_stems) != 1:
        raise ExperimentalRewriteError(
            "Cubase writer currently requires exactly one active pool item"
        )

    mutable = bytearray(data)
    for offset in length_offsets:
        if offset >= delete_start or offset + 4 > len(mutable):
            raise ExperimentalRewriteError(f"Unsafe 32-bit length field at 0x{offset:x}")
        old = struct.unpack(">I", mutable[offset:offset + 4])[0]
        if old < delta:
            raise ExperimentalRewriteError(
                f"Length at 0x{offset:x} is smaller than removal"
            )
        mutable[offset:offset + 4] = struct.pack(">I", old - delta)
    mutable[child_count_offset:child_count_offset + 4] = struct.pack(">I", 1)

    reference_offsets: List[int] = []
    cursor = delete_end
    while cursor <= arrangement.end - 4:
        if mutable[cursor] == 0x80:
            word = struct.unpack(">I", mutable[cursor:cursor + 4])[0]
            target = word & 0x7FFFFFFF
            if delete_end <= target < arrangement.end:
                mutable[cursor:cursor + 4] = struct.pack(
                    ">I", 0x80000000 | (target - delta)
                )
                reference_offsets.append(cursor)
                cursor += 4
                continue
        cursor += 1
    if len(reference_offsets) != 3:
        raise ExperimentalRewriteError(
            f"Expected three shifted 32-bit references, found {len(reference_offsets)}"
        )

    del mutable[delete_start:delete_end]
    output = bytes(mutable)
    if struct.unpack(">I", output[4:8])[0] != len(output) - 12:
        raise ExperimentalRewriteError("Generated RIFF length does not validate")
    for name in pool_only:
        if name.encode("utf-8") in output:
            raise ExperimentalRewriteError(f"Generated data still contains {name}")

    audit = RewriteAudit(
        source_sha256=hashlib.sha256(data).hexdigest(),
        output_sha256=hashlib.sha256(output).hexdigest(),
        delete_start=delete_start,
        delete_end=delete_end,
        deleted_bytes=delta,
        pool_only_names=pool_only,
        length_fields=length_offsets,
        reference_fields=reference_offsets,
        delete_ranges=[(delete_start, delete_end)],
    )
    return output, audit


def rewrite_for_exact_profile(source: Path) -> Tuple[bytes, RewriteAudit]:
    parsed = parse_project(source)
    if parsed.container == "RIF2" and parsed.version in SUPPORTED_NUENDO_RIF2_VERSIONS:
        return rewrite_remove_pool_only(source)
    if parsed.container == "RIFF" and parsed.version == "12.0.70":
        return rewrite_remove_pool_only_cubase12(source)
    raise ExperimentalRewriteError(
        f"No experimental writer for {parsed.container} {parsed.version}"
    )


def write_new_file(source: Path, destination: Path) -> RewriteAudit:
    if destination.exists():
        raise ExperimentalRewriteError(f"Destination already exists: {destination}")
    output, audit = rewrite_for_exact_profile(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Unique per attempt; see _atomic_json in transaction.py.
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as handle:
        handle.write(output)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    audit = write_new_file(args.source, args.destination)
    print(f"EXPERIMENTAL output: {args.destination}")
    print(f"Deleted bytes: {audit.deleted_bytes}")
    print(f"Pool-only names: {', '.join(audit.pool_only_names)}")
    print(f"Adjusted references: {len(audit.reference_fields)}")
    print(f"SHA-256: {audit.output_sha256}")


if __name__ == "__main__":
    main()
