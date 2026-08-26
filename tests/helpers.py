import struct
from pathlib import Path


def chunk(tag: bytes, payload: bytes, container="RIF2") -> bytes:
    length = struct.pack(">Q", len(payload)) if container == "RIF2" else struct.pack(">I", len(payload))
    return tag + length + payload


def root(name: str, class_name: str, container="RIF2") -> bytes:
    a, b = name.encode(), class_name.encode()
    return chunk(
        b"ROOT", struct.pack(">I", len(a)) + a + struct.pack(">I", len(b)) + b,
        container,
    )


def text_field(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">I", len(raw) + 4) + raw + b"\x00\xef\xbb\xbf"


def make_project(path: Path, active=(), unused=(), version="15.0.30", container="RIF2", active_paths=()) -> None:
    body = bytearray()
    body += root("Version", "PAppVersion", container)
    body += chunk(
        b"ARCH", b"\x00\x00\x00\x07Nuendo\x00Version " + version.encode() + b"\x00",
        container,
    )
    body += root("Arrangement1", "PArrangement", container)
    arrangement = bytearray(b"MAudioTrackEvent\x00")
    hints = list(active_paths)
    for index, name in enumerate(active):
        hint = hints[index].encode("utf-8") if index < len(hints) else b""
        arrangement += text_field(name) + hint + b"PMediaDescriptor\x00"
    arrangement += b"\x00\x00\x00\x06PPool"
    for name in active:
        arrangement += text_field(name) + b"GTreeEntry\x00"
    for name in unused:
        arrangement += text_field(name) + b"PMediaDescriptor\x00"
    body += chunk(b"ARCH", bytes(arrangement), container)
    if container == "RIF2":
        data = b"RIF2" + struct.pack(">Q", len(body)) + b"NUND" + body
    else:
        data = b"RIFF" + struct.pack(">I", len(body)) + b"NUND" + body
    path.write_bytes(data)
