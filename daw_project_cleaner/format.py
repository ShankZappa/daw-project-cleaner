"""Strict, read-only parser for understood Steinberg NUND containers.

It intentionally does not deserialize or write project object graphs. The
reader accepts the inspected 64-bit ``RIF2/NUND`` and 32-bit ``RIFF/NUND``
outer containers. Every profile is report-only in the public release. A media
filename seen before the single PPool boundary has active-side evidence; one
seen only after it has pool-side-only evidence.
"""
from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


AUDIO_EXTENSIONS = {
    ".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3", ".ogg",
    ".m4a", ".aac", ".w64", ".rf64", ".caf",
}
AUDIO_NAME_RE = re.compile(
    rb"^[^/\\\x00\r\n]{1,255}\.(?:wav|wave|aif|aiff|flac|mp3|ogg|m4a|aac|w64|rf64|caf)$",
    re.IGNORECASE,
)
VERSION_RE = re.compile(rb"Version\s+([0-9]+(?:\.[0-9]+){1,3})")
PRODUCT_RE = re.compile(rb"\x00\x00\x00\x07(Cubase|Nuendo)\x00")
POOL_MARKER = b"\x00\x00\x00\x06PPool"


class ProjectFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Chunk:
    tag: str
    offset: int
    payload_offset: int
    length: int
    end: int
    name: Optional[str] = None
    class_name: Optional[str] = None


@dataclass
class ParsedProject:
    sha256: str
    container: str
    product: Optional[str]
    version: Optional[str]
    serialization_profile: str
    confidence: str
    pool_offset: int
    chunks: List[Chunk]
    occurrences: Dict[str, List[int]]
    warnings: List[str]


def _decode_root(payload: bytes) -> Tuple[Optional[str], Optional[str]]:
    if len(payload) < 8:
        return None, None
    n1 = struct.unpack(">I", payload[:4])[0]
    split = 4 + n1
    if split + 4 > len(payload):
        return None, None
    n2 = struct.unpack(">I", payload[split:split + 4])[0]
    if split + 4 + n2 != len(payload):
        return None, None
    try:
        return (
            payload[4:split].decode("utf-8", "strict"),
            payload[split + 4:].decode("utf-8", "strict"),
        )
    except UnicodeDecodeError:
        return None, None


def parse_chunks(data: bytes) -> List[Chunk]:
    if len(data) >= 16 and data[:4] == b"RIF2":
        container = "RIF2"
        form = data[12:16]
        declared = struct.unpack(">Q", data[4:12])[0]
        expected = len(data) - 16
        offset = 16
        length_size = 8
    elif len(data) >= 12 and data[:4] == b"RIFF":
        container = "RIFF"
        form = data[8:12]
        declared = struct.unpack(">I", data[4:8])[0]
        expected = len(data) - 12
        offset = 12
        length_size = 4
    else:
        raise ProjectFormatError("not a supported RIF2/RIFF container")
    if form != b"NUND":
        raise ProjectFormatError(f"unsupported {container} form {form!r}")
    if declared != expected:
        raise ProjectFormatError(
            f"container length mismatch ({declared} != {expected})"
        )
    chunks: List[Chunk] = []
    while offset < len(data):
        header_size = 4 + length_size
        if offset + header_size > len(data):
            raise ProjectFormatError(f"truncated chunk header at 0x{offset:x}")
        raw_tag = data[offset:offset + 4]
        try:
            tag = raw_tag.decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise ProjectFormatError(f"non-ASCII chunk tag at 0x{offset:x}") from exc
        length_format = ">Q" if length_size == 8 else ">I"
        length = struct.unpack(
            length_format, data[offset + 4:offset + header_size]
        )[0]
        payload_offset = offset + header_size
        end = payload_offset + length
        if end > len(data):
            raise ProjectFormatError(f"chunk {tag} at 0x{offset:x} exceeds file")
        name = class_name = None
        if tag == "ROOT":
            name, class_name = _decode_root(data[payload_offset:end])
        chunks.append(Chunk(tag, offset, payload_offset, length, end, name, class_name))
        offset = end
    if offset != len(data):
        raise ProjectFormatError("chunks do not cover the complete file")
    return chunks


def _extract_audio_fields(data: bytes) -> Dict[str, List[int]]:
    occurrences: Dict[str, List[int]] = {}
    sentinel = b"\x00\xef\xbb\xbf"
    cursor = 0
    while True:
        end = data.find(sentinel, cursor)
        if end < 0:
            break
        cursor = end + len(sentinel)
        for text_len in range(1, min(255, end) + 1):
            start = end - text_len
            if start < 4:
                break
            if struct.unpack(">I", data[start - 4:start])[0] != text_len + 4:
                continue
            raw = data[start:end]
            if not AUDIO_NAME_RE.fullmatch(raw):
                break
            try:
                name = raw.decode("utf-8", "strict")
            except UnicodeDecodeError:
                break
            occurrences.setdefault(name, []).append(start)
            break
    return occurrences


def _class_version(data: bytes, name: str, start: int, end: int) -> Optional[int]:
    raw = name.encode("ascii") + b"\x00"
    marker = struct.pack(">I", len(raw)) + raw
    found = data.find(marker, start, end)
    if found < 0 or found + len(marker) + 2 > end:
        return None
    return struct.unpack(">H", data[found + len(marker):found + len(marker) + 2])[0]


def parse_project(path: Path) -> ParsedProject:
    data = path.read_bytes()
    container = data[:4].decode("ascii", "replace")
    chunks = parse_chunks(data)
    warnings: List[str] = []

    arrangements = [c for c in chunks if c.tag == "ROOT" and c.class_name == "PArrangement"]
    if len(arrangements) != 1:
        raise ProjectFormatError(f"expected one PArrangement ROOT, found {len(arrangements)}")
    arrangement = arrangements[0]
    index = chunks.index(arrangement)
    if index + 1 >= len(chunks) or chunks[index + 1].tag != "ARCH":
        raise ProjectFormatError("PArrangement is not followed by ARCH")
    arrangement_arch = chunks[index + 1]

    pool_positions = []
    cursor = arrangement_arch.payload_offset
    while True:
        found = data.find(POOL_MARKER, cursor, arrangement_arch.end)
        if found < 0:
            break
        pool_positions.append(found + 4)
        cursor = found + len(POOL_MARKER)
    if len(pool_positions) != 1:
        raise ProjectFormatError(
            f"expected one PPool boundary inside arrangement, found {len(pool_positions)}"
        )
    pool_offset = pool_positions[0]
    occurrences = _extract_audio_fields(data)
    if not occurrences:
        warnings.append("No supported audio filename fields were found")

    version_match = VERSION_RE.search(data[:min(len(data), 4096)])
    version = version_match.group(1).decode("ascii") if version_match else None
    product_match = PRODUCT_RE.search(data[:min(len(data), 4096)])
    product = product_match.group(1).decode("ascii") if product_match else None
    major = int(version.split(".")[0]) if version else None
    versions = {
        "PA": _class_version(
            data, "PArrangement", arrangement_arch.payload_offset, pool_offset
        ),
        "MR": _class_version(data, "MRoot", arrangement_arch.payload_offset, pool_offset),
        "PP": _class_version(data, "PPool", pool_offset - 4, min(arrangement_arch.end, pool_offset + 64)),
        "GT": _class_version(data, "GTree", pool_offset, min(arrangement_arch.end, pool_offset + 128)),
        "GE": _class_version(data, "GTreeEntry", pool_offset, min(arrangement_arch.end, pool_offset + 192)),
    }
    width = 64 if container == "RIF2" else 32
    serialization_profile = (
        f"{container}{width}/chunks{len(chunks)}/" +
        "/".join(f"{key}v{value if value is not None else '?'}" for key, value in versions.items())
    )
    confidence = "high" if container == "RIF2" and major == 15 else "review"
    if container == "RIFF":
        warnings.append(
            "The 32-bit RIFF/NUND profile is readable but cleanup remains disabled"
        )
    if confidence != "high":
        warnings.append(
            f"Serialization profile {serialization_profile} is report-only"
        )
    return ParsedProject(
        sha256=hashlib.sha256(data).hexdigest(),
        container=container,
        product=product,
        version=version,
        serialization_profile=serialization_profile,
        confidence=confidence,
        pool_offset=pool_offset,
        chunks=chunks,
        occurrences=occurrences,
        warnings=warnings,
    )
